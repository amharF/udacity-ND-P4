App Engine application for the Udacity training course.

## Products
- [App Engine][1]

## Language
- [Python][2]

## APIs
- [Google Cloud Endpoints][3]

## Setup Instructions
1. Update the value of `application` in `app.yaml` to the app ID you
   have registered in the App Engine admin console and would like to use to host
   your instance of this sample.
2. Update the values at the top of `settings.py` to
   reflect the respective client IDs you have registered in the
   [Developer Console][4].
3. Update the value of CLIENT_ID in `static/js/app.js` to the Web client ID
4. (Optional) Mark the configuration files as unchanged as follows:
   `$ git update-index --assume-unchanged app.yaml settings.py static/js/app.js`
5. Run the app with the devserver using `dev_appserver.py DIR`, and ensure it's running by visiting your local server's address (by default [localhost:8080][5].)
6. (Optional) Generate your client library(ies) with [the endpoints tool][6].
7. Deploy your application.


[1]: https://developers.google.com/appengine
[2]: http://python.org
[3]: https://developers.google.com/appengine/docs/python/endpoints/
[4]: https://console.developers.google.com/
[5]: https://localhost:8080/
[6]: https://developers.google.com/appengine/docs/python/endpoints/endpoints_tool


##Deploying the application
1. launch GoogleAppEngineLauncher
2. go to: file > Add existing application > select folder '00_Conference_Central'
3. click on the Logs button to open logs viewer
4. click on Deploy. Check log viewer for message: "*** appcfg.py has finished with exit code 0 ***". You have succesfully deployed the app. 
5. testing API endpoint methods:

-Access API backend (deployed) with API explorer, go to:

https://your_app_id.appspot.com/_ah/api/explorer

OR

https://apis-explorer.appspot.com/apis-explorer/?base=https://your_app_id.appspot.com/_ah/api#p/conference/v1/

where 'your_app_id.appspot.com' is the client ID you registered in the Developer Console
6. viewing Datastore data: from GoogleAppEngineLauncher, click on 'Dashboard', this redirects to https://console.developers.google.com/home/dashboard?project=your_app_id





Task 1)

I have chosen to implement the Session entities as children of a Conference entity. If there are more than one conference using the conference websafe key it is easier to retrieve all associated session entities. Also it makes more sense since a session is an event in a confenrece. In the response I have included the session's own websafe key.

Speakers I have chosen to implement as stringfields. Although it would have been possible to create Speakers as seperate entities, I did not think it was worthwhile since later in task 4 all speaker related reponses are stored in memchache using queues

Regarding the data modelling choices, I have chosen to add:
-Session class: this creates session entities in Datastore
	-name (StringProperty, required): each session needs as a minimum a name
	-highlights (StringProperty, repeated): noteworthy higlights of a session, multiple possible
	-speaker (StringProperty): name of the speaker 
	-duration (IntegerProperty): how long the session lasts in whole hours
	-sessionType (StringProperty): the type denomination of session, for the sake of this assigment exercise it can be: workshop, keynote or lecture. A session can only have one type
	-date (DateProperty): date in format yyyy-mm-dd, although most sessions will fall  on the same dates as conferences, there could be edge cases (eg. a concert starting at 24.00) where it would be useful for a session object to have its own date. 
	-startTime (TimeProperty): time in format h:m, where h takes values of 0-24 and m takes values of 0-59
-SessionForm protorpc class: follows the Session model data types but additionally includes the websafeKey and organiserDisplayName to include in the API response:
	-name (StringField): each session needs as a minimum a name
	-highlights (StringField, repeated): noteworthy higlights of a session, multiple possible
	-speaker (StringField): name of the speaker
	-duration (StringField): how long the session lasts in whole hours
	-sessionType (StringField): the type denomination of session, for the sake of this assigment exercise it can be: workshop, keynote or lecture. A session can only have one type
	-date (StringField): date in format yyyy-mm-dd
	-starttime (StringField): time in format h:m, where h takes values of 0-24 and takes values of 0-59
	-websafeKey (StringField): websafe version of session key
	organizerDisplayName (StringField): name of conference organizer creating a session
-SessionForms protorpc in case of returning multiple session objects in a response:
	-items:
-SessionQueryForm as Session query inbound form message
	-field:
	-operator:
	-value:
-SessionQueryForms as multiple SessionQueryForm inbound form messages
	-filters:

Be sure to enter into all date fields the date as YYYY-MM-DD (eg. 2015-06-04)
Be sure to enter into all time fields the time as HH (eg. 18 for 18.00 or 6pm)

Task 2) 

Users are able to add/remove sessions to/from their wishlist and then query for the sessions in the wishlist. Next to the API endpoint mehtods I have added a sessionKeystoAttend field to the Profile and ProfileForm classes. This is effectively the 'wishlist' where the keys of the desired sessions are stored. 


Task 3a)

For all queries the API can execute a entry has been added to the index.yaml file. I have checked for any missing enties and tested while deployed to Appspot. 

Task 3b)

Query1 ('getTeeShirtsForConference'): because each conference has many attendees, the organisers have to know how many t-shirts to order and in what sizes. The endpoint will return a dict object containing all participants attending the conference and their t-shirt sizes, so the conference team know what to order at the t-shirt shop. 

Query2 ('getConferenceSessionInSummer'): because business slows down in the summer, this is the ideal time for prospective participants to attend sessions in a conference. But first they need to know which sessions actually takke place in the summer. This query filters sessions by the summer season 06/21/2015-09/22/2015 and returns those sessions (if any - tip: use createSession endpoint to make a summer conference for testing purposes).

Task 3c)

Datastore rejects queries using inequality filtering on more than one property. Inequality filters are limited to at most one property per query. A single query may not use inequality comparisons (<, <=, >, >=, !=) on more than one property across all of its filters. 

If querying for sessions that are not workshops (eg. Session.sessionType != 'worksop') and starting before 7pm (eg. Session.starTime < 7pm) you would be applying two different inequlity filters across two different properties in a single query which is not allowded. The query as follows would not be allowed:

sessions = Session.query(Session.sessionType != 'workshop', Session.startTime < date)

Solution:

I have developped the getPreferredSessions endpoint which: a) queries on one property and fetches the results, (eg. Session.sessionType != 'workshop') b) creates an empty list variable c) loops through the fetched list with a conditional that checks whether Session.startTime < 7pm. If true then appends to the empty list d) returns the list. See API endpoint 'getPreferredSessions' in conferency.py.

The drawback of doing this is that it is more computational heavy for the server since you have to loop through your results each time. However, for the purpose of the exercise - to organize a conference that contains sessions - it is unlikely there will ever be more than a handful of sessions per day and so the method response latency is kelp minimal. 

Task 4)

I have done a number of things to implement this:

conference.py:
-in _createSessionObject I added a check to validate a speaker has been passed in the 
request. If so, I add an entry to the task queue that passes on the conference websafekey and speaker name, which I will use later as filter arguments. Also the specific url to trigger the task is passed along. 
-added a local method _chacheFeaturedSpeaker which takes as imputs the websafekey and speaker name. It then queries datastore taking in aforementioned imputs as filter arguments, fetches results and checks that mthere are more than 1 session in the results. If so, a memchace entry is done. 
-added an API endpoint method getFeaturedSpeaker which retrieves the memchache entry.

main.py:
-added a url to the app definition that will call the setFeatueredSpeakerHandler
-added setFeatueredSpeakerHandler class to call the _chacheFeaturedSpeaker method in conference.py

app.yaml:
-added an entry for the set_featured_speaker task








