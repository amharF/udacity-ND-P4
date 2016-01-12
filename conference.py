#!/usr/bin/env python

"""
conference.py -- Udacity conference server-side Python App Engine API;
    uses Google Cloud Endpoints

$Id: conference.py,v 1.25 2014/05/24 23:42:19 wesc Exp wesc $

created by wesc on 2014 apr 21

modified on 2015 dec 21 by Amhar.Ford@Gmail.com as part of Nanodegree 
Project 4: Conference Organisation App

"""

__author__ = 'wesc+api@google.com (Wesley Chun), amhar.ford@gmail.com'


from datetime import datetime
from datetime import date
from datetime import time

import endpoints

from protorpc import messages
from protorpc import message_types
from protorpc import remote

from google.appengine.api import memcache
from google.appengine.api import taskqueue

from google.appengine.ext import ndb

from models import ConflictException
from models import Profile
from models import ProfileMiniForm
from models import ProfileForm
from models import BooleanMessage
from models import Conference
from models import ConferenceForm
from models import ConferenceForms
from models import ConferenceQueryForm
from models import ConferenceQueryForms
from models import TeeShirtSize
from models import StringMessage
from models import Session
from models import SessionForm
from models import SessionForms


from utils import getUserId

from settings import WEB_CLIENT_ID


EMAIL_SCOPE = endpoints.EMAIL_SCOPE
API_EXPLORER_CLIENT_ID = endpoints.API_EXPLORER_CLIENT_ID
MEMCACHE_ANNOUNCEMENTS_KEY = "RECENT_ANNOUNCEMENTS"
MEMCACHE_FEATURED_SPEAKER_KEY = 'FEATURED_SPEAKER'

# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -

DEFAULTS = {
    "city": "Default City",
    "maxAttendees": 0,
    "seatsAvailable": 0,
    "topics": [ "Default", "Topic" ],
}

SESSION_DEFAULTS = {
    "highlights": [ "Default", "Highlight" ],
    "speaker": "Default Speaker",
    "duration": 0,
    "sessionType": "Default Type",
}

OPERATORS = {
            'EQ':   '=',
            'GT':   '>',
            'GTEQ': '>=',
            'LT':   '<',
            'LTEQ': '<=',
            'NE':   '!=',
            }

FIELDS =    {
            'CITY': 'city',
            'TOPIC': 'topics',
            'MONTH': 'month',
            'MAX_ATTENDEES': 'maxAttendees',
            'SPEAKER': 'speaker',
            'TYPE': 'sessionType',
            }

CONF_GET_REQUEST = endpoints.ResourceContainer(
    message_types.VoidMessage,
    websafeConferenceKey=messages.StringField(1),
)

CONF_POST_REQUEST = endpoints.ResourceContainer(
    ConferenceForm,
    websafeConferenceKey=messages.StringField(1),
)

SESSION_GET_REQUEST = endpoints.ResourceContainer(
    message_types.VoidMessage,
    websafeConferenceKey=messages.StringField(1),
    sessionType=messages.StringField(2),
    sessionSpeaker=messages.StringField(3),
    websafeSessionKey=messages.StringField(4),
)

SESSION_POST_REQUEST = endpoints.ResourceContainer(
    SessionForm,
    websafeConferenceKey=messages.StringField(1),
    
)

#I have seperate get request template for the sake of testing out how this works
#in the API endpoint
SPEAKER_SESSION_GET_REQUEST = endpoints.ResourceContainer(
    message_types.VoidMessage,
    speaker=messages.StringField(1),
)


# - - - Create Conference API endpoint - - - - - - - - - - - - - - 


@endpoints.api(name='conference', version='v1', 
    allowed_client_ids=[WEB_CLIENT_ID, API_EXPLORER_CLIENT_ID],
    scopes=[EMAIL_SCOPE])
class ConferenceApi(remote.Service):
    """Conference API v0.1"""

# - - - Conference objects - - - - - - - - - - - - - - - - - - - -

    @endpoints.method(ConferenceForm, ConferenceForm, path='conference',
            http_method='POST', name='createConference')
    def createConference(self, request):
        """Create new conference."""
        return self._createConferenceObject(request)

    @endpoints.method(CONF_POST_REQUEST, ConferenceForm,
            path='conference/{websafeConferenceKey}',
            http_method='PUT', name='updateConference')
    def updateConference(self, request):
        """Update conference w/provided fields & return w/updated info."""
        return self._updateConferenceObject(request)

    def _createConferenceObject(self, request):
        """Create or update Conference object, return 
        ConferenceForm/request."""
        # preload necessary data items
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        user_id = getUserId(user)

        if not request.name:
            raise endpoints.BadRequestException(
                "Conference 'name' field required")

        # copy ConferenceForm/ProtoRPC Message into dict
        data = {field.name: getattr(request, field.name) for field in \
                request.all_fields()}
        del data['websafeKey']
        del data['organizerDisplayName']

        # add default values for those missing (both data model & outbound Message)
        for df in DEFAULTS:
            if data[df] in (None, []):
                data[df] = DEFAULTS[df]
                setattr(request, df, DEFAULTS[df])

        # convert dates from strings to Date objects; set month based on start_date
        if data['startDate']:
            data['startDate'] = datetime.strptime(data['startDate'][:10],\
             "%Y-%m-%d").date()
            data['month'] = data['startDate'].month
        else:
            data['month'] = 0
        if data['endDate']:
            data['endDate'] = datetime.strptime(data['endDate'][:10],\
             "%Y-%m-%d").date()

        # set seatsAvailable to be same as maxAttendees on creation
        if data["maxAttendees"] > 0:
            data["seatsAvailable"] = data["maxAttendees"]
        # generate Profile Key based on user ID and Conference
        # ID based on Profile key get Conference key from ID
        p_key = ndb.Key(Profile, user_id)
        c_id = Conference.allocate_ids(size=1, parent=p_key)[0]
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

    @ndb.transactional()
    def _updateConferenceObject(self, request):
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        user_id = getUserId(user)

        # copy ConferenceForm/ProtoRPC Message into dict
        data = {field.name: getattr(request, field.name) for field in \
                request.all_fields()}

        # update existing conference
        conf = ndb.Key(urlsafe=request.websafeConferenceKey).get()
        # check that conference exists
        if not conf:
            raise endpoints.NotFoundException(
                'No conference found with key: %s' % request.websafeConferenceKey)

        # check that user is owner
        if user_id != conf.organizerUserId:
            raise endpoints.ForbiddenException(
                'Only the owner can update the conference.')

        # Not getting all the fields, so don't create a new object; just
        # copy relevant fields from ConferenceForm to Conference object
        for field in request.all_fields():
            data = getattr(request, field.name)
            # only copy fields where we get data
            if data not in (None, []):
                # special handling for dates (convert string to Date)
                if field.name in ('startDate', 'endDate'):
                    data = datetime.strptime(data, "%Y-%m-%d").date()
                    if field.name == 'startDate':
                        conf.month = data.month
                # write to Conference object
                setattr(conf, field.name, data)
        conf.put()
        prof = ndb.Key(Profile, user_id).get()
        return self._copyConferenceToForm(conf, getattr(prof, 'displayName'))

    @endpoints.method(CONF_GET_REQUEST, ConferenceForm,
            path='conference/{websafeConferenceKey}',
            http_method='GET', name='getConference')
    def getConference(self, request):
        """Return requested conference (by websafeConferenceKey)."""
        # get Conference object from request; bail if not found
        conf = ndb.Key(urlsafe=request.websafeConferenceKey).get()
        if not conf:
            raise endpoints.NotFoundException(
                'No conference found with key: %s' % request.websafeConferenceKey)
        prof = conf.key.parent().get()
        # return ConferenceForm
        return self._copyConferenceToForm(conf, getattr(prof, 'displayName'))

    @endpoints.method(message_types.VoidMessage, ConferenceForms,
            path='getConferencesCreated',
            http_method='POST', name='getConferencesCreated')
    def getConferencesCreated(self, request):
        """Return conferences created by user."""
        # make sure user is authed
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        user_id =  getUserId(user)
        # create ancestor query for all key matches for this user
        confs = Conference.query(ancestor=ndb.Key(Profile, user_id))
        prof = ndb.Key(Profile, user_id).get()
        # return set of ConferenceForm objects per Conference
        return ConferenceForms(
            items=[self._copyConferenceToForm(conf, 
                getattr(prof, 'displayName')) for conf in confs]
        )

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

    @endpoints.method(ConferenceQueryForms, ConferenceForms,
            path='queryConferences',
            http_method='POST',
            name='queryConferences')
    def queryConferences(self, request):
        """Query for conferences."""
        conferences = self._getQuery(request)

        # need to fetch organiser displayName from profiles
        # get all keys and use get_multi for speed
        organisers = [(ndb.Key(Profile, 
            conf.organizerUserId)) for conf in conferences]
        profiles = ndb.get_multi(organisers)

        # put display names in a dict for easier fetching
        names = {}
        for profile in profiles:
            names[profile.key.id()] = profile.displayName

        # return individual ConferenceForm object per Conference
        return ConferenceForms(
                items=[self._copyConferenceToForm(conf, 
                    names[conf.organizerUserId]) for conf in conferences])

    def _getQuery(self, request):
        """Return formatted query from the submitted filters."""
        q = Conference.query()
        inequality_filter, filters = self._formatFilters(request.filters)

        # If exists, sort on inequality filter first
        if not inequality_filter:
            q = q.order(Conference.name)
        else:
            q = q.order(ndb.GenericProperty(inequality_filter))
            q = q.order(Conference.name)

        for filtr in filters:
            if filtr["field"] in ["month", "maxAttendees"]:
                filtr["value"] = int(filtr["value"])
            formatted_query = ndb.query.FilterNode(filtr["field"], 
                filtr["operator"], filtr["value"])
            q = q.filter(formatted_query)
        return q

    def _formatFilters(self, filters):
        """Parse, check validity and format user supplied filters."""
        formatted_filters = []
        inequality_field = None

        for f in filters:
            filtr = {field.name: getattr(f, field.name) for \
                field in f.all_fields()}

            try:
                filtr["field"] = FIELDS[filtr["field"]]
                filtr["operator"] = OPERATORS[filtr["operator"]]
            except KeyError:
                raise endpoints.BadRequestException(
                    "Filter contains invalid field or operator.")

            # Every operation except "=" is an inequality
            if filtr["operator"] != "=":
                # check if inequality operation has been used in previous filters
                # disallow the filter if inequality was performed on a different 
                # field before track the field on which the inequality operation
                # is performed
                if inequality_field and inequality_field != filtr["field"]:
                    raise endpoints.BadRequestException(
                        "Inequality filter is allowed on only one field.")
                else:
                    inequality_field = filtr["field"]

            formatted_filters.append(filtr)
        return (inequality_field, formatted_filters)

# - - - Task 1: Add sessions to a conference - - - - - - - - - - - -

    @endpoints.method(SESSION_POST_REQUEST, SessionForm, 
            path='session/{websafeConferenceKey}',
            http_method='POST', name='createSession')
    def createSession(self, request):
        """Create new session."""
        return self._createSessionObject(request)

    def _createSessionObject(self, request):
        """Create or update Session object, returning SessionForm/request."""

        # if request does not contain a name for a session raise and error
        if not request.name:
            raise endpoints.BadRequestException("Session 'name' field required")

        # retrieve conference object using websafekey
        # validate that given websafe key points to an actual conference object
        conf = ndb.Key(urlsafe=request.websafeConferenceKey).get()
        if not conf:
            raise endpoints.NotFoundException(
                'No conference found with key: %s' % request.websafeConferenceKey)

        # retrieve current user submitting request, then get their user ID
        user = endpoints.get_current_user()
        user_id = getUserId(user)

        # check that user ID matches organizerID of conference as
        # only the organizer of a conference can create sessions in it
        if user_id != conf.organizerUserId:
            raise endoints.UnauthorizedException("You have to be the \
                conference organizer to add sessions to it!")

        # copy SessionForm/ProtoRPC Message into a dictionary variable
        data = {field.name: getattr(request, field.name) for field in \
            request.all_fields()}
        
        # delete fields that will be recreated with property values from Datastore
        del data['websafeKey']
        del data['websafeConferenceKey']
        del data['organizerDisplayName']

        # add default values for those missing (both data model & outbound Message)
        for df in SESSION_DEFAULTS:
            if data[df] in (None, []):
                data[df] = SESSION_DEFAULTS[df]

        # convert dates from strings to Date objects; 
        if data['date']:
            data['date'] = datetime.strptime(data['date'][:10], "%Y-%m-%d").date()
        if data['startTime']:
            data['startTime'] = datetime.strptime(data['startTime'][:10], "%H:%M").time()

        # get Conference key from request key
        c_key = ndb.Key(urlsafe=request.websafeConferenceKey)

        # generate Session ID based on Conference key 
        s_id = Session.allocate_ids(size=1, parent=c_key)[0]

        # generate Session key from Session ID with conf key as parent
        s_key = ndb.Key(Session, s_id, parent=c_key) 

        # add property value previously removed back to the data variable
        data['key'] = s_key

        # creation of Session in Datastore
        Session(**data).put()

        # obtain the newly created session object
        sess = s_key.get()
        
        # check if there is a speaker in the request, if so add to task queue
        if request.speaker:
            
            # pass websafekey and speaker name from request to task queue
            taskqueue.add(params={
                'websafeConferenceKey': request.websafeConferenceKey,
                'sessionSpeaker': request.speaker},
                url='/tasks/set_featured_speaker'
            )

        # return response request in required format
        return self._copySessionToForm(sess)

        
    def _copySessionToForm(self, sess):
        """Copy relevant fields from Session to SessionForm."""
        sf = SessionForm()
        for field in sf.all_fields():
            if hasattr(sess, field.name):
                # convert Date to date string; just copy others
                if field.name.endswith('date'):
                    setattr(sf, field.name, str(getattr(sess, field.name)))
                elif field.name.endswith('Time'):
                    setattr(sf, field.name, str(getattr(sess, field.name)))
                else:
                    setattr(sf, field.name, getattr(sess, field.name))
        setattr(sf, 'websafeKey', str(sess.key.urlsafe()))

        sf.check_initialized()
        return sf

    @endpoints.method(SESSION_GET_REQUEST, SessionForms, 
            path='sessions/all/{websafeConferenceKey}',
            http_method='GET', name='getConferenceSessions')
    def getConferenceSessions(self, request):
        """Return sessions by conference."""

        # fetch conference by key in the request
        conference_key = ndb.Key(urlsafe=request.websafeConferenceKey)
        
        # query and return sessions by conference key
        sessions = Session.query(ancestor=conference_key).fetch()

        return SessionForms(
            items=[self._copySessionToForm(sess) for sess in sessions]
        )


    @endpoints.method(SESSION_GET_REQUEST, SessionForms,
            path='sessions/sessionType/{websafeConferenceKey}/{sessionType}',
            http_method='GET', 
            name='getConferenceSessionByType')
    def getConferenceSessionByType(self, request):
        """Query sessions and filter by type"""
        
        # get speaker as object from request
        requestType = request.sessionType

        # fetch conference key from request 
        conference_key = ndb.Key(urlsafe=request.websafeConferenceKey)

        # query Session by conference key
        # filter sessions by request type and sort by name
        sessions = Session.query(ancestor=conference_key).filter(
            Session.sessionType == requestType).order(Session.name).fetch()
        
        return SessionForms(
            items=[self._copySessionToForm(sess) for sess in sessions]
        )

    @endpoints.method(SPEAKER_SESSION_GET_REQUEST, SessionForms,
            path='conferences/speaker/{speaker}',
            http_method='GET', 
            name='getConferenceSessionBySpeaker')
    def getConferenceSessionBySpeaker(self, request):
        """Query sessions and filter by speaker"""

        # get speaker as object from request
        requestSpeaker = request.speaker

        # query Session class, filter by speaker than order sessions
        sessions = Session.query(Session.speaker == requestSpeaker).order(
            Session.name).fetch()

        return SessionForms(
            items=[self._copySessionToForm(sess) for sess in sessions]
        )        

# - - - Task 2: Add sessions to user wishlist - - - - - - - - -

    @endpoints.method(SESSION_GET_REQUEST, BooleanMessage,
            path='profile/wishlist/{websafeSessionKey}',
            http_method='POST', name='addSessionToWishlist')
    def addSessionToWishlist(self, request):
        """Register user for selected session."""
        return self._sessionRegistration(request)

    @endpoints.method(SESSION_GET_REQUEST, BooleanMessage,
            path='profile/wishlist/{websafeSessionKey}',
            http_method='DELETE', name='deleteSessionInWishlist')
    def deleteSessionInWishlist(self, request):
        """Unregister user for selected session."""
        return self._sessionRegistration(request, reg=False)    

    @ndb.transactional(xg=True)
    def _sessionRegistration(self, request, reg=True):
        """Register or unregister user for selected session."""
        retval = None
        prof = self._getProfileFromUser() # get user Profile

        # check if session exists given websafeSessionKey
        # get session; check that it exists
        wssk = request.websafeSessionKey
        key = ndb.Key(urlsafe=wssk)
        session = key.get()
        
        # raise error if 'session' has no value
        if not session:
            raise endpoints.NotFoundException(
                'No session found with key: %s' % wssk)

        # add session to user wishlist
        # 'reg' was sent to True as method argument
        if reg:
            # check if user already added session otherwise raise error
            if key in prof.sessionKeysToAttend:
                raise ConflictException(
                    "You have already registered for this session")

            # add session key to user profile as a wishlist item
            prof.sessionKeysToAttend.append(key)
            retval = True

        # remove session from user wishlist
        else:
            # check if user already added session
            if key in prof.sessionKeysToAttend:

                # remove session key from user profile
                prof.sessionKeysToAttend.remove(key)
                retval = True
            else:
                retval = False

        # write things back to the datastore & return
        prof.put()
        # return a Boolean value for response to confirm session
        # has been added
        return BooleanMessage(data=retval)

    @endpoints.method(message_types.VoidMessage, SessionForms,
            path='profile/wishlist',
            http_method='GET', 
            name='getSessionsInWishlist')
    def getSessionsInWishlist(self, request):
        """Query profile object for sessions in wishlist"""

        # return profile entity
        prof = self._getProfileFromUser()

        # return list of session websafe keys in profile entity
        session_keys = prof.sessionKeysToAttend
        
        # create empty variable to store session entities in
        sessions = []

        # loop over list to return session entities and append to 
        #empty list
        for key in session_keys:
            # fetch session entity
            session = key.get()
            
            # append session entity to empty list
            sessions.append(session)

        return SessionForms(
            items=[self._copySessionToForm(sess) for sess in sessions]
        )

# - - - Task 3: work on indexes and queries - - - - - - - - - - -

    @endpoints.method(CONF_GET_REQUEST, StringMessage,
            path='conference/teeShirts/{websafeConferenceKey}',
            http_method='GET', name='getTeeShirtsForConference')
    def getTeeShirtsForConference(self, request):
        """For registered conference attendees, return their 
        TeeShirt sizes."""
        
        # retrieve websafekey from request
        wsck = request.websafeConferenceKey
        key = ndb.Key(urlsafe=wsck)

        # if there is no value for websafekey raise an error
        if not wsck:
            raise endpoints.NotFoundException(
                'Not a valid websafe conference key: %s' % wsck)
        
        # query all profiles for given websafe key
        profiles = Profile.query(
            Profile.conferenceKeysToAttend == key).fetch()

        tshirt_dict = {profile.displayName: profile.teeShirtSize for profile in profiles}

        return StringMessage(data=str(tshirt_dict))

    @endpoints.method(message_types.VoidMessage, SessionForms,
            path='sessions/summer',
            http_method='GET', 
            name='getConferenceSessionInSummer')
    def getConferenceSessionInSummer(self, request):
        """Query sessions and filter by month"""

        # query Session class, filter by speaker than order sessions
        # filter for sessions occuring in the summer season
        # sort sessions by date
        sessions = Session.query(Session.date >= date(2015,6,21), \
        Session.date <= date(2015,9,22)).order(Session.date).fetch()
        
        return SessionForms(
            items=[self._copySessionToForm(sess) for sess in sessions]
        )

    @endpoints.method(message_types.VoidMessage, SessionForms,
            path='sessions/preferred',
            http_method='GET',
            name='getPreferredSessions')
    def getPreferredSessions(self, request):
        """Query sessions that are not workshops and start before 7pm"""

        # query sessions for non-workshops
        sessions = Session.query(Session.sessionType != 'workshop').fetch()

        # create empty lists to store preferred session and their websafe keys in
        pref_sessions = []

        # loop through the list of non-workshops 
        for i in range(len(sessions)):
            # if condition of 7pm starttime is met, append to empty lists
            if sessions[i].startTime < time(19):
                pref_sessions.append(sessions[i])

        # return response ready form for each session key in list
        return SessionForms(
            items=[self._copySessionToForm(sess) for sess in pref_sessions]
        )

# - - - Task 4: add a task - - - - - - - - - - - - - - - -

    @staticmethod
    def _cacheFeaturedSpeaker(websafeConferenceKey,sessionSpeaker):
        """Create featured speaker announcement & set to memcache"""
        
        # retrieve conference key 
        c_key = ndb.Key(urlsafe=websafeConferenceKey)

        # query all sessions associated with the conference
        # filter query by speaker name in request
        sessions = Session.query(ancestor=c_key).filter(
            Session.speaker == sessionSpeaker).order(Session.name).fetch()

        # if there is more than one session with the same speaker, 
        # set message to memcache
        if len(sessions) > 1:
            featured_speaker = '%s %s %s' % (
                'The following sessions '
                'feature the main speaker',
                sessionSpeaker+':',
                ', '.join(session.name for session in sessions))
            # set the memcache for the most recent speaker and their sessions
            memcache.set(MEMCACHE_FEATURED_SPEAKER_KEY, featured_speaker)
            
        # return empty if condition is not met
        else:
            featured_speaker = ""

        return featured_speaker

    @endpoints.method(message_types.VoidMessage, StringMessage,
            path='conference/featured_speaker/get',
            http_method='GET', name='getFeaturedSpeaker')
    def getFeaturedSpeaker(self, request):
        """Return featured speaker from memcache."""
        
        # return an existing announcement from Memcache or an empty message.
        featured_speaker = memcache.get(MEMCACHE_FEATURED_SPEAKER_KEY)
        
        return StringMessage(data=featured_speaker or "no featured speaker to return")


# - - - Profile objects - - - - - - - - - - - - - - - - - - - -

    def _copyProfileToForm(self, prof):
        """Copy relevant fields from Profile to ProfileForm."""
        # copy relevant fields from Profile to ProfileForm
        pf = ProfileForm()

        for field in pf.all_fields():
            if hasattr(prof, field.name):
                # convert t-shirt string to Enum; just copy others
                if field.name == 'teeShirtSize':
                    setattr(pf, field.name, getattr(TeeShirtSize, 
                        getattr(prof, field.name)))
                elif field.name == 'conferenceKeysToAttend':
                    setattr(pf, field.name, [conf.urlsafe() for conf \
                        in prof.conferenceKeysToAttend])    
                elif field.name == 'sessionKeysToAttend':
                    setattr(pf, field.name, [sess.urlsafe() for sess \
                        in prof.sessionKeysToAttend])
                else:
                    setattr(pf, field.name, getattr(prof, field.name))
        pf.check_initialized()
        return pf

    def _getProfileFromUser(self):
        """Return user Profile from datastore, creating new one 
        if non-existent."""
        # make sure user is authed
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')

        # get Profile from datastore
        user_id = getUserId(user)
        p_key = ndb.Key(Profile, user_id)
        profile = p_key.get()
        # create new Profile if not there
        if not profile:
            profile = Profile(
                key = p_key,
                displayName = user.nickname(),
                mainEmail= user.email(),
                teeShirtSize = str(TeeShirtSize.NOT_SPECIFIED),
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
                        #if field == 'teeShirtSize':
                        #    setattr(prof, field, str(val).upper())
                        #else:
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


# - - - Registration - - - - - - - - - - - - - - - - - - - -

    @endpoints.method(CONF_GET_REQUEST, BooleanMessage,
            path='conference/{websafeConferenceKey}',
            http_method='POST', name='registerForConference')
    def registerForConference(self, request):
        """Register user for selected conference."""
        return self._conferenceRegistration(request)

    @endpoints.method(CONF_GET_REQUEST, BooleanMessage,
            path='conference/{websafeConferenceKey}',
            http_method='DELETE', name='unregisterFromConference')
    def unregisterFromConference(self, request):
        """Unregister user for selected conference."""
        return self._conferenceRegistration(request, reg=False)

    @ndb.transactional(xg=True)
    def _conferenceRegistration(self, request, reg=True):
        """Register or unregister user for selected conference."""
        retval = None
        prof = self._getProfileFromUser() # get user Profile


        # check if conf exists given websafeConfKey
        # get conference; check that it exists
        wsck = request.websafeConferenceKey
        key = ndb.Key(urlsafe=wsck)
        conf = key.get()
        if not conf:
            raise endpoints.NotFoundException(
                'No conference found with key: %s' % wsck)

        # register
        if reg:
            # check if user already registered otherwise add
            if key in prof.conferenceKeysToAttend:
                raise ConflictException(
                    "You have already registered for this conference")

            # check if seats avail
            if conf.seatsAvailable <= 0:
                raise ConflictException(
                    "There are no seats available.")

            # register user, take away one seat
            prof.conferenceKeysToAttend.append(key)
            conf.seatsAvailable -= 1
            retval = True

        # unregister
        else:
            # check if user already registered
            if key in prof.conferenceKeysToAttend:

                # unregister user, add back one seat
                prof.conferenceKeysToAttend.remove(key)
                conf.seatsAvailable += 1
                retval = True
            else:
                retval = False

        # write things back to the datastore & return
        prof.put()
        conf.put()
        return BooleanMessage(data=retval)

    @endpoints.method(message_types.VoidMessage, ConferenceForms,
            path='conferences/attending',
            http_method='GET', name='getConferencesToAttend')
    def getConferencesToAttend(self, request):
        """Get list of conferences that user has registered for."""
        prof = self._getProfileFromUser() # get user Profile
        
        # get conference entities from confernece keys stoted in profile
        conferences = ndb.get_multi(prof.conferenceKeysToAttend)

        # get organizers
        organisers = [ndb.Key(Profile, conf.organizerUserId) for \
                conf in conferences]
        profiles = ndb.get_multi(organisers)

        # put display names in a dict for easier fetching
        names = {}
        for profile in profiles:
            names[profile.key.id()] = profile.displayName

        # return set of ConferenceForm objects per Conference
        return ConferenceForms(items=[self._copyConferenceToForm(conf, 
            names[conf.organizerUserId]) for conf in conferences]
        )

# - - - Announcements - - - - - - - - - - - - - - - - - - - -

    @staticmethod
    def _cacheAnnouncement():
        """Create Announcement & assign to memcache; used by
        memcache cron job & putAnnouncement().
        """
        confs = Conference.query(ndb.AND(
            Conference.seatsAvailable <= 5,
            Conference.seatsAvailable > 0)
        ).fetch(projection=[Conference.name])

        if confs:
            # If there are almost sold out conferences,
            # format announcement and set it in memcache
            announcement = '%s %s' % (
                'Last chance to attend! The following conferences '
                'are nearly sold out:',
                ', '.join(conf.name for conf in confs))
            memcache.set(MEMCACHE_ANNOUNCEMENTS_KEY, announcement)
        else:
            # If there are no sold out conferences,
            # delete the memcache announcements entry
            announcement = ""
            memcache.delete(MEMCACHE_ANNOUNCEMENTS_KEY)

        return announcement

    @endpoints.method(message_types.VoidMessage, StringMessage,
            path='conference/announcement/get',
            http_method='GET', name='getAnnouncement')
    def getAnnouncement(self, request):
        """Return Announcement from memcache."""
        
        # return an existing announcement from Memcache or an empty string.
        announcement = memcache.get(MEMCACHE_ANNOUNCEMENTS_KEY)
        if not announcement:
            announcement = ""
        return StringMessage(data=announcement)


api = endpoints.api_server([ConferenceApi]) # register API
