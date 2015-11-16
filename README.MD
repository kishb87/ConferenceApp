# Udacity Fullstack Nanodegree Project 4 -- Conference Organization App

### Description

This app was created as the fourth project in the Udacity Full Stack
Nanodegree.

This is a python based project that utilizes Google App Engine to create APIs that are accessible from a web-based conference organization app.

The conference application can be accessed [here](https://udacityconferenceapp-1987.appspot.com/). The APIs for the application can be accessed through the [API explorer](https://udacityconferenceapp-1987.appspot.com/_ah/api/explorer)

### Setting Up
1. Create an application in [Google App Engine](http://console.developers.google.com)
2. Rename the application in app.yaml to application you created in App Engine
3. Update the client ID in settings.py
4. Update the client ID in static/js/app.js

### Using Google App Engine Launcher
1. Download [Google App Engine SDK for Python](https://cloud.google.com/appengine/downloads?hl=en)
2. Load the Google App Engine Launcher
3. Go to File --> Add Existing Application
4. Set directory to the location of this application
5. Run locally by pressing Run
6. Deploy to App Engine by pressing Deploy

### Access APIs
To access APIs, visit: https://{your-app-id}.appspot.com/_ah/api/explorer

##### Notes Regarding Project Requirements

Task 1: Add Sessions to Conference

This task requires that the application supports the ability to add sessions to conferences. The following endpoints were created in order to allow this.
	
	- getConferenceSessions(websafeConferenceKey) -- Given a conference, return all sessions
	- getConferenceSessionsByType(websafeConferenceKey, typeOfSession) Given a conference, return all sessions of a specified type (eg lecture, keynote, workshop)
	- getSessionsBySpeaker(speaker) -- Given a speaker, return all sessions given by this particular speaker, across all conferences
	- createSession(SessionForm, websafeConferenceKey) -- open to the organizer of the conference

For the Session class, I used primarily StringFields in the data model in order to allow for unicode string values. This serves useful for name of the session, highlights, speaker name, the type of session, and the conference key. I used the integer property for the duration of the session and the time property for the start of the session. Only the speaker name is required. The SessionForm class is modeled identically and this is used for the outbound form message.

Task 3: Solve the following query related problem

Question: Let’s say that you don't like workshops and you don't like sessions after 7 pm. How would you handle a query for all non-workshop sessions before 7 pm? What is the problem for implementing this query? What ways to solve it did you think of?

Answer: This is a question with two properties that need to be filtered. This is an issue in datastore because it can only support one inequality filter for each property in a query. This could however be done with two seperate queries.

In regards to Task 4, I created a chron job for the scheduled task. It will check for the featured
speaker once every hour.