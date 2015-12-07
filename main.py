#!/usr/bin/env python
import webapp2
from google.appengine.api import app_identity
from google.appengine.api import mail
from google.appengine.api import memcache
from google.appengine.ext import ndb
from conference import ConferenceApi
from conference import MEMCACHE_FEATURED_SPEAKER_KEY
from models import Session


class SendConfirmationEmailHandler(webapp2.RequestHandler):

    def post(self):
        """Send email confirming Conference creation."""
        mail.send_mail(
            'noreply@%s.appspotmail.com' % (
                app_identity.get_application_id()),     # from
            self.request.get('email'),                  # to
            'You created a new Conference!',            # subj
            'Hi, you have created a following '         # body
            'conference:\r\n\r\n%s' % self.request.get(
                'conferenceInfo')
        )


class CheckFeaturedSpeakerHandler(webapp2.RequestHandler):

    def post(self):
        """Check if added speaker is already speaking at conference.
        If so, add as Featured Speaker to memecache"""

        # get speaker from newly created session
        speaker = self.request.get('speaker')
        session_array = []

        # get websafeConferenceKey and then get conference object
        wsck = self.request.get('wsck')
        conf = ndb.Key(urlsafe=wsck).get()

        # get all sessions for conference with ancestry query
        conference_sessions = Session.query(ancestor=conf.key)

        # store all instances of speaker speaking at conference
        for session in conference_sessions:
            if session.speaker == speaker:
                session_array.append(str(session.name))

        # if speaker is speaking more than once, add to memcache
        if len(session_array) > 1:
            # create unique memcache key for conference (using conf key):
            memcache_key = MEMCACHE_FEATURED_SPEAKER_KEY + str(wsck)

            # create string of all sessions by speaker
            session_string = ', '.join(session_array)

            # set memcache on datastore using key, speaker, and output:
            memcache.set(memcache_key, "Featured speaker is: {}. Sessions include: {}"
                                       "".format(speaker,
                                                 session_string))


class SetAnnouncementHandler(webapp2.RequestHandler):

    def get(self):
        """Set Announcement in Memcache."""
        ConferenceApi._cacheAnnouncement()
        self.response.set_status(204)

app = webapp2.WSGIApplication([
    ('/crons/set_announcement', SetAnnouncementHandler),
    ('/tasks/send_confirmation_email', SendConfirmationEmailHandler),
    ('/tasks/check_featured_speaker', CheckFeaturedSpeakerHandler)
], debug=True)
