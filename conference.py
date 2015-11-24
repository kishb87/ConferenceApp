#!/usr/bin/env python

"""
conference.py -- Udacity conference server-side Python App Engine API;
    uses Google Cloud Endpoints

$Id: conference.py,v 1.25 2014/05/24 23:42:19 wesc Exp wesc $

created by wesc on 2014 apr 21

"""

__author__ = 'wesc+api@google.com (Wesley Chun)'


from datetime import datetime
import json
import os
import time

import endpoints
from protorpc import messages
from protorpc import message_types
from protorpc import remote

from google.appengine.api import urlfetch
from google.appengine.ext import ndb
from google.appengine.api import memcache
from google.appengine.api import taskqueue

from models import *

from utils import getUserId

from settings import *


DEFAULTS = {
    "city": "Default City",
    "maxAttendees": 0,
    "seatsAvailable": 0,
    "topics": ["Default", "Topic"],
}

OPERATORS = {
    'EQ':   '=',
            'GT':   '>',
            'GTEQ': '>=',
            'LT':   '<',
            'LTEQ': '<=',
            'NE':   '!='
}

FIELDS = {
    'CITY': 'city',
            'TOPIC': 'topics',
            'MONTH': 'month',
            'MAX_ATTENDEES': 'maxAttendees',
}


EMAIL_SCOPE = endpoints.EMAIL_SCOPE
API_EXPLORER_CLIENT_ID = endpoints.API_EXPLORER_CLIENT_ID

CONF_GET_REQUEST = endpoints.ResourceContainer(
    message_types.VoidMessage,
    websafeConferenceKey=messages.StringField(1),
)

SESSION_GET_REQUEST = endpoints.ResourceContainer(
    message_types.VoidMessage,
    typeOfSession=messages.StringField(1),
    websafeConferenceKey=messages.StringField(2),
)

SESSION_GET_BY_SPEAKER_REQUEST = endpoints.ResourceContainer(
    message_types.VoidMessage,
    speaker=messages.StringField(1),

)

SESSION_GET_BY_HIGHLIGHTS_REQUEST = endpoints.ResourceContainer(
    message_types.VoidMessage,
    highlights=messages.StringField(1),

)

SESSION_REQUEST = endpoints.ResourceContainer(
    message_types.VoidMessage,
    sessionKey=messages.StringField(1),
)

MEMCACHE_ANNOUNCEMENTsession_key = "RECENT_ANNOUNCEMENTS"
MEMCACHE_FEATURED_SPEAKER_KEY = "FEATURED_SPEAKER"
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -


@endpoints.api(name='conference', version='v1', audiences=[ANDROID_AUDIENCE],
               allowed_client_ids=[
                   WEB_CLIENT_ID, API_EXPLORER_CLIENT_ID, ANDROID_CLIENT_ID, IOS_CLIENT_ID],
               scopes=[EMAIL_SCOPE])
class ConferenceApi(remote.Service):

    """Conference API v0.1"""

# - - - Profile objects - - - - - - - - - - - - - - - - - - -

    def _copyProfileToForm(self, prof):
        """Copy relevant fields from Profile to ProfileForm."""
        # copy relevant fields from Profile to ProfileForm
        pf = ProfileForm()
        for field in pf.all_fields():
            if hasattr(prof, field.name):
                # convert t-shirt string to Enum; just copy others
                if field.name == 'teeShirtSize':
                    setattr(
                        pf, field.name, getattr(TeeShirtSize, getattr(prof, field.name)))
                else:
                    setattr(pf, field.name, getattr(prof, field.name))
        pf.check_initialized()
        return pf

    def _getProfileFromUser(self):
        """Return user Profile from datastore, creating new one if non-existent."""
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        user_id = getUserId(user)
        p_key = ndb.Key(Profile, user_id)
        profile = p_key.get()
        if not profile:
            profile = Profile(
                key=p_key,
                displayName=user.nickname(),
                mainEmail=user.email(),
                teeShirtSize=str(TeeShirtSize.NOT_SPECIFIED),
            )
            profile.put()

        return profile      # return Profile

    def _doProfile(self, save_request=None):
        """Get user Profile and return to user, possibly updating it first."""
        # get user Profile
        prof = self._getProfileFromUser()

        # if saveProfile(), process user-modifyable fields
        if save_request:
            for field in ('displayName', 'teeShirtSize'):
                if hasattr(save_request, field):
                    val = getattr(save_request, field)
                    if val:
                        setattr(prof, field, str(val))
                        # if field == 'teeShirtSize':
                        #    setattr(prof, field, str(val).upper())
                        # else:
                        #    setattr(prof, field, val)
                        prof.put()

        # return ProfileForm
        return self._copyProfileToForm(prof)

    @endpoints.method(message_types.VoidMessage, ProfileForm,
                      path='profile', http_method='GET', name='getProfile')
    def getProfile(self, request):
        """Return user profile."""
        return self._doProfile()

    @endpoints.method(ProfileMiniForm, ProfileForm,
                      path='profile', http_method='POST', name='saveProfile')
    def saveProfile(self, request):
        """Update & return user profile."""
        return self._doProfile(request)

# - - - Conference objects - - - - - - - - - - - - - - - - -
    def _copyConferenceToForm(self, conf, displayName):
        """Copy relevant fields from Conference to ConferenceForm."""
        cf = ConferenceForm()
        for field in cf.all_fields():
            if hasattr(conf, field.name):
                # convert Date to date string; just copy others
                if field.name.endswith('Date'):
                    setattr(cf, field.name, str(getattr(conf, field.name)))
                else:
                    setattr(cf, field.name, getattr(conf, field.name))
            elif field.name == "websafeKey":
                setattr(cf, field.name, conf.key.urlsafe())
        if displayName:
            setattr(cf, 'organizerDisplayName', displayName)
        cf.check_initialized()
        return cf

    def _createConferenceObject(self, request):
        """Create or update Conference object, returning ConferenceForm/request."""
        # Check if user is logged in
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        user_id = getUserId(user)

        if not request.name:
            raise endpoints.BadRequestException(
                "Conference 'name' field required")

        # Copy ConferenceForm/ProtoRPC Message into dict
        data = {field.name: getattr(request, field.name)
                for field in request.all_fields()}
        del data['websafeKey']
        del data['organizerDisplayName']

        # Add default values for missing fields
        for default_value in DEFAULTS:
            if data[default_value] in (None, []):
                data[default_value] = DEFAULTS[default_value]
                setattr(request, default_value, DEFAULTS[default_value])

        # Convert date strings to Date objects
        if data['startDate']:
            data['startDate'] = datetime.strptime(
                data['startDate'][:10], "%Y-%m-%d").date()
            data['month'] = data['startDate'].month
        else:
            data['month'] = 0
        if data['endDate']:
            data['endDate'] = datetime.strptime(
                data['endDate'][:10], "%Y-%m-%d").date()

        # set seatsAvailable to be same as maxAttendees on creation
        # both for data model & outbound Message
        if data["maxAttendees"] > 0:
            data["seatsAvailable"] = data["maxAttendees"]
            setattr(request, "seatsAvailable", data["maxAttendees"])

        # make Profile Key from user ID
        p_key = ndb.Key(Profile, user_id)
        # allocate new Conference ID with Profile key as parent
        c_id = Conference.allocate_ids(size=1, parent=p_key)[0]
        # make Conference key from ID
        c_key = ndb.Key(Conference, c_id, parent=p_key)
        data['key'] = c_key
        data['organizerUserId'] = request.organizerUserId = user_id

        # create Conference, send email to organizer confirming
        # creation of Conference & return (modified) ConferenceForm
        Conference(**data).put()
        taskqueue.add(params={'email': user.email(),
                              'conferenceInfo': repr(request)},
                      url='/tasks/send_confirmation_email'
                      )

        return request

    def _formatFilters(self, filters):
        """Parse, check validity and format user supplied filters."""
        formatted_filters = []
        inequality_field = None

        for f in filters:
            filter_item = {field.name: getattr(f, field.name)
                           for field in f.all_fields()}

            try:
                filter_item["field"] = FIELDS[filter_item["field"]]
                filter_item["operator"] = OPERATORS[filter_item["operator"]]
                print filter_item
            except KeyError:
                raise endpoints.BadRequestException(
                    "Filter contains invalid field or operator.")

            # Every operation except "=" is an inequality
            if filter_item["operator"] != "=":
                # check if inequality operation has been used in previous filters
                # disallow the filter if inequality was performed on a different field before
                # track the field on which the inequality operation is
                # performed
                if inequality_field and inequality_field != filter_item["field"]:
                    raise endpoints.BadRequestException(
                        "Inequality filter is allowed on only one field.")
                else:
                    inequality_field = filter_item["field"]

            formatted_filters.append(filter_item)
        return (inequality_field, formatted_filters)

    @ndb.transactional(xg=True)
    def _conferenceRegistration(self, request, reg=True):
        """Register or unregister user for selected conference."""
        retval = None
        prof = self._getProfileFromUser()  # get user Profile

        # check if conf exists given websafeConfKey
        # get conference; check that it exists
        web_conf_key = request.websafeConferenceKey
        conf = ndb.Key(urlsafe=web_conf_key).get()
        if not conf:
            raise endpoints.NotFoundException(
                'No conference found with key: %s' % web_conf_key)

        # register
        if reg:
            # check if user already registered otherwise add
            if web_conf_key in prof.conferenceKeysToAttend:
                raise ConflictException(
                    "You have already registered for this conference")

            # check if seats avail
            if conf.seatsAvailable <= 0:
                raise ConflictException(
                    "There are no seats available.")

            # register user, take away one seat
            prof.conferenceKeysToAttend.append(web_conf_key)
            conf.seatsAvailable -= 1
            retval = True

        # unregister
        else:
            # check if user already registered
            if web_conf_key in prof.conferenceKeysToAttend:

                # unregister user, add back one seat
                prof.conferenceKeysToAttend.remove(web_conf_key)
                conf.seatsAvailable += 1
                retval = True
            else:
                retval = False

        # write things back to the datastore & return
        prof.put()
        conf.put()
        return BooleanMessage(data=retval)

    def _getQuery(self, request):
        """Return formatted query from the submitted filters."""
        q = Conference.query()
        inequality_filter, filters = self._formatFilters(request.filters)

        # If query exists then sort by inequality filter first
        if not inequality_filter:
            q = q.order(Conference.name)
        else:
            q = q.order(ndb.GenericProperty(inequality_filter))
            q = q.order(Conference.name)

        for filter_item in filters:
            if filter_item["field"] in ["month", "maxAttendees"]:
                filter_item["value"] = int(filter_item["value"])
            formatted_query = ndb.query.FilterNode(
                filter_item["field"], filter_item["operator"], filter_item["value"])
            q = q.filter(formatted_query)
        return q

    @endpoints.method(ConferenceQueryForms, ConferenceForms,
                      path='queryConferences',
                      http_method='POST',
                      name='queryConferences')
    def queryConferences(self, request):
        """Query for conferences."""
        conferences = self._getQuery(request)

        # need to fetch organiser displayName from profiles
        # get all keys and use get_multi for speed
        organisers = [(ndb.Key(Profile, conf.organizerUserId))
                      for conf in conferences]
        profiles = ndb.get_multi(organisers)

        # put display names in a dict for easier fetching
        names = {}
        for profile in profiles:
            names[profile.key.id()] = profile.displayName

        # return individual ConferenceForm object per Conference
        return ConferenceForms(
            items=[self._copyConferenceToForm(conf, names[conf.organizerUserId]) for conf in
                   conferences]
        )

    @endpoints.method(message_types.VoidMessage, ConferenceForms,
                      path='filterPlayground',
                      http_method='GET',
                      name='filterPlayground')
    def filterPlayground(self, request):
        """Query for conferences filter by city."""
        q = Conference.query()
        field = "city"
        operator = "="
        value = "London"
        # Uses FilterNode method
        f = ndb.query.FilterNode(field, operator, value)
        q = q.filter(f)
        # return individual ConferenceForm object per Conference
        return ConferenceForms(
            items=[self._copyConferenceToForm(conf, "") for conf in q]
        )

    @endpoints.method(message_types.VoidMessage, ConferenceForms,
                      path='getSmallConferences',
                      http_method='GET',
                      name='getSmallConferences')
    def getSmallConferences(self, request):
        """Query for conferences filter by max attendees of 50 or fewer."""
        q = Conference.query()
        field = "maxAttendees"
        operator = "<"
        value = 51
        # Uses FilterNode method
        f = ndb.query.FilterNode(field, operator, value)
        q = q.filter(f)
        # return individual ConferenceForm object per Conference
        return ConferenceForms(
            items=[self._copyConferenceToForm(conf, "") for conf in q]
        )

    @endpoints.method(ConferenceForm, ConferenceForm, path='conference',
                      http_method='POST', name='createConference')
    def createConference(self, request):
        """Create new conference."""
        return self._createConferenceObject(request)

    @endpoints.method(message_types.VoidMessage, ConferenceForms, path='getConferencesCreated',
                      http_method='POST', name='getConferencesCreated')
    def getConferencesCreated(self, request):
        """Return conferences created by user."""
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        user_id = getUserId(user)
        p_key = ndb.Key(Profile, user_id)
        conferences = Conference.query(ancestor=p_key)
        prof = ndb.Key(Profile, user_id).get()
        displayName = getattr(prof, 'displayName')

        return ConferenceForms(items=[self._copyConferenceToForm(conf, displayName) for conf in conferences])

    @endpoints.method(CONF_GET_REQUEST, BooleanMessage,
                      path='conference/{websafeConferenceKey}',
                      http_method='POST', name='registerForConference')
    def registerForConference(self, request):
        """Register user for selected conference."""
        return self._conferenceRegistration(request)

    @endpoints.method(SessionForm, SessionForm,
                      path='createSession',
                      http_method='POST', name='createSession')
    def createSession(self, request):
        """Create a session in a given conference; open only to the organizer of this conference."""
        return self._createSessionObject(request)

    @endpoints.method(CONF_GET_REQUEST, SessionForms,
                      path='conference/{websafeConferenceKey}/sessions',
                      http_method='GET', name='getConferenceSessions')
    def getConferenceSessions(self, request):
        """Returns all sessions within a given conference."""
        # Get the conference key
        web_conf_key = request.websafeConferenceKey
        # Get the conference with the given target key
        conf = ndb.Key(urlsafe=web_conf_key).get()
        # Check conference existance
        if not conf:
            raise endpoints.NotFoundException(
                'No conference found with key: %s' % web_conf_key)
        # Create ancestor query
        sessions = Session.query()
        Sessions = sessions.filter(
            Session.websafeConferenceKey == web_conf_key)
        return SessionForms(items=[self._copySessionToForm(session) for session in sessions])

    @endpoints.method(SESSION_GET_REQUEST, SessionForms,
                      path='conference/{websafeConferenceKey}/sessions/{typeOfSession}',
                      http_method='GET', name='getConferenceSessionsByType')
    def getConferenceSessionsByType(self, request):
        """Given a conference, return all sessions of a specified type (e.g. lecture, keynote, workshop)."""
        # get the conference key
        web_conf_key = request.websafeConferenceKey
        # get the type pf session we want
        typeOfSession = request.typeOfSession
        # fetch the conference with the target key
        conf = ndb.Key(urlsafe=web_conf_key).get()
        # check whether the conference exists or not
        if not conf:
            raise endpoints.NotFoundException(
                'No conference found with key: %s' % web_conf_key)
        # create ancestor query for all key matches for this conference and
        # type is what we want
        sessions = Session.query()
        sessions = sessions.filter(
            Session.typeOfSession == typeOfSession, Session.websafeConferenceKey == web_conf_key)
        # return set of SessionForm objects per Session
        return SessionForms(items=[self._copySessionToForm(session) for session in sessions])

    @endpoints.method(SESSION_GET_BY_SPEAKER_REQUEST, SessionForms,
                      path='/sessions/{speaker}',
                      http_method='GET', name='getSessionsBySpeaker')
    def getSessionsBySpeaker(self, request):
        """Given a speaker, return all sessions given by this particular speaker, across all conferences."""
        sessions = Session.query()
        sessions = sessions.filter(Session.speaker == request.speaker)
        # return set of SessionForm objects
        return SessionForms(items=[self._copySessionToForm(session) for session in sessions])

    @endpoints.method(SESSION_GET_BY_HIGHLIGHTS_REQUEST, SessionForms,
                      path='/sessions/{highlights}',
                      http_method='GET', name='getSessionsByHighlights')
    def getSessionsByHighlights(self, request):
        """Given a specified highlight, return all sessions with this specific highlight, across all conferences."""
        sessions = Session.query()
        sessions = sessions.filter(Session.highlights == request.highlights)
        # return set of SessionForm objects
        return SessionForms(items=[self._copySessionToForm(session) for session in sessions])


    @endpoints.method(message_types.VoidMessage, ConferenceForms,
                      path='conferences/attending',
                      http_method='GET', name='getConferencesToAttend')
    def getConferencesToAttend(self, request):
        """Get list of conferences that user has registered for."""
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        prof = self._getProfileFromUser()  # get user Profile
        conf_keys = [ndb.Key(urlsafe=web_conf_key)
                     for web_conf_key in prof.conferenceKeysToAttend]
        conferences = ndb.get_multi(conf_keys)

        # get organizers
        organisers = [ndb.Key(Profile, conf.organizerUserId)
                      for conf in conferences]
        profiles = ndb.get_multi(organisers)

        # put display names in a dict for easier fetching
        names = {}
        for profile in profiles:
            names[profile.key.id()] = profile.displayName

        # return set of ConferenceForm objects per Conference
        return ConferenceForms(items=[self._copyConferenceToForm(conf, names[conf.organizerUserId])
                                      for conf in conferences]
                               )

    @endpoints.method(message_types.VoidMessage, BooleanMessage,
                      path='clearAllData', http_method='GET',
                      name='clearAllData')
    def clearAllData(self, request):
        """Clear all the data saved."""
        ndb.delete_multi(Session.query().fetch(keys_only=True))
        ndb.delete_multi(Conference.query().fetch(keys_only=True))
        profiles = Profile.query()
        for profile in profiles:
            profile.conferenceKeysToAttend = []
            profile.sessionKeysInWishlist = []
            profile.put()
        return BooleanMessage(data=True)
# - - - Session Objects - - - - - - - - - - - - - - - - -

    def _copySessionToForm(self, session):
        """Copy relevant fields from Session to SessionForm."""
        session_objects = SessionForm()
        for field in session_objects.all_fields():
            if hasattr(session, field.name):
                if field.name.endswith('date') or field.name.endswith('startTime'):
                    setattr(session_objects, field.name,
                            str(getattr(session, field.name)))
                else:
                    setattr(session_objects, field.name,
                            getattr(session, field.name))
            elif field.name == "sessionSafeKey":
                setattr(session_objects, field.name, session.key.urlsafe())
        session_objects.check_initialized()
        return session_objects

    def _createSessionObject(self, request):
        """Create or update Conference object, returning SessionForm/request."""
        # Check user authenetication
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        user_id = getUserId(user)

        if not request.name:
            raise endpoints.BadRequestException(
                "Session 'name' field required")

        # Get conference key
        web_conf_key = request.websafeConferenceKey
        # Get conference object
        c_key = ndb.Key(urlsafe=web_conf_key)
        conf = c_key.get()
        # Check that conference exists if not then raise error
        if not conf:
            raise endpoints.NotFoundException(
                'No conference found with key: %s' % web_conf_key)
        # Check that the user is the creator of the conference
        if conf.organizerUserId != getUserId(endpoints.get_current_user()):
            raise endpoints.ForbiddenException(
                'You must be the organizer to create a session.')

        # Copy the SessionForm/ProtoRPC Message into dict
        data = {field.name: getattr(request, field.name)
                for field in request.all_fields()}
        # Convert date and time from strings to Date objects;
        if data['date']:
            data['date'] = datetime.strptime(
                data['date'][:10], "%Y-%m-%d").date()
        if data['startTime']:
            data['startTime'] = datetime.strptime(
                data['startTime'][:10],  "%H, %M").time()
        # Create new Session ID with Conference key as the parent
        session_id = Session.allocate_ids(size=1, parent=c_key)[0]
        # Make Session key from ID
        session_key = ndb.Key(Session, session_id, parent=c_key)
        data['key'] = session_key
        data['websafeConferenceKey'] = web_conf_key
        del data['sessionSafeKey']

        # Save session into database
        Session(**data).put()
        # Taskque to send a confirmation email to the creator
        taskqueue.add(params={'email': user.email(),
                              'conferenceInfo': repr(request)},
                      url='/tasks/send_confirmation_session_email'
                      )
        return request

    @endpoints.method(SESSION_REQUEST, SessionForm,
                      path="addSessionToWishlist",
                      http_method="POST", name='addSessionToWishlist')
    def addSessionToWishlist(self, request):
        """Add the session to the user's list of sessions they are interested in attending"""
        # Get the session key
        sessionKey = request.sessionKey
        # Get the session object
        session = ndb.Key(urlsafe=sessionKey).get()
        # Check that session exists or not
        if not session:
            raise endpoints.NotFoundException(
                'No session found with key: %s' % sessionKey)

        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')

        profile = self._getProfileFromUser()
        if not profile:
            raise endpoints.BadRequestException(
                'Profile does not exist for user')
        # Check if key and Session match
        if not type(ndb.Key(urlsafe=sessionKey).get()) == Session:
            raise endpoints.NotFoundException(
                'This key is not a Session instance')
        # Add the session to wishlist
        if sessionKey not in profile.sessionKeysInWishlist:
            try:
                profile.sessionKeysInWishlist.append(sessionKey)
                profile.put()
            except Exception:
                raise endpoints.InternalServerErrorException(
                    'Error in storing the wishlist')
        return self._copySessionToForm(session)

    @endpoints.method(message_types.VoidMessage, SessionForms,
                      path='getSessionsInWishlist', http_method='GET',
                      name='getSessionsInWishlist')
    def getSessionsInWishlist(self, request):
        """Query for all the sessions in a conference that the user is interested in."""
        profile = self._getProfileFromUser()
        if not profile:
            raise endpoints.BadRequestException(
                'Profile does not exist for user')
        # Get all of the session keys in db
        sessionkeys = [ndb.Key(urlsafe=sessionkey)
                       for sessionkey in profile.sessionKeysInWishlist]
        sessions = ndb.get_multi(sessionkeys)
        # Return set of SessionForm objects per conference
        return SessionForms(items=[self._copySessionToForm(session) for session in sessions])

# - - - Featured Speaker - - - - - - - - - - - - - - - - -
    @staticmethod
    def _cacheFeaturedSpeaker():
        """Get Featured Speaker & assign to memcache;"""
        sessions = Session.query()
        speakersCounter = {}
        featured_speaker = ""
        num = 0
        for session in sessions:
            if session.speaker:
                if session.speaker not in speakersCounter:
                    speakersCounter[session.speaker] = 1
                else:
                    speakersCounter[session.speaker] += 1
                if speakersCounter[session.speaker] > num:
                    featured_speaker = session.speaker
                    num = speakersCounter[session.speaker]
        memcache.set(MEMCACHE_FEATURED_SPEAKER_KEY, featured_speaker)
        return featured_speaker

    @endpoints.method(message_types.VoidMessage, StringMessage,
                      path='speaker/get_features',
                      http_method='GET', name='getFeaturedSpeaker')
    def getFeaturedSpeaker(self, request):
        """Get all featured speakers"""
        featured_speaker = memcache.get(MEMCACHE_FEATURED_SPEAKER_KEY)
        if not featured_speaker:
            featured_speaker = ""
        # return json data
        return StringMessage(data=json.dumps(featured_speaker))


# - - - Annoucement - - - - - - - - - - - - - - - - -
    @staticmethod
    def _cacheAnnouncement():
        """Create Announcement and assign to memcache
        """
        confs = Conference.query(ndb.AND(
            Conference.seatsAvailable <= 5,
            Conference.seatsAvailable > 0)
        ).fetch(projection=[Conference.name])

        if confs:
            # Send to memcache when conferences are almost sold out
            announcement = '%s %s' % (
                'Act soon! The following conferences '
                'are almost sold out:',
                ', '.join(conf.name for conf in confs))
            memcache.set(MEMCACHE_ANNOUNCEMENTsession_key, announcement)
        else:
            # Delete the memcache announcements entry when conference is not
            # sold out
            announcement = ""
            memcache.delete(MEMCACHE_ANNOUNCEMENTsession_key)

        return announcement

    @endpoints.method(message_types.VoidMessage, StringMessage,
                      path='conference/announcement/get',
                      http_method='GET', name='getAnnouncement')
    def getAnnouncement(self, request):
        """Get Announcement from memcache."""
        announcement = memcache.get(MEMCACHE_ANNOUNCEMENTsession_key)
        if not announcement:
            announcement = ""
        return StringMessage(data=announcement)

# registers API
api = endpoints.api_server([ConferenceApi])
