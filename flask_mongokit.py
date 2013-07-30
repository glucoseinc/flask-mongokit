# -*- coding: utf-8 -*-
"""
    flask.ext.mongokit
    ~~~~~~~~~~~~~~~~~~

    Flask-MongoKit simplifies to use MongoKit, a powerful MongoDB ORM in Flask
    applications.

    :copyright: 2011 by Christoph Heer <Christoph.Heer@googlemail.com
    :license: BSD, see LICENSE for more details.
"""
from __future__ import absolute_import

import bson
from mongokit import Connection, Database, Collection, Document

from werkzeug.routing import BaseConverter
from flask import abort, _request_ctx_stack

try: # pragma: no cover
    from flask import _app_ctx_stack
    ctx_stack = _app_ctx_stack
except ImportError: # pragma: no cover
    ctx_stack = _request_ctx_stack

class AuthenticationIncorrect(Exception):
    pass

class BSONObjectIdConverter(BaseConverter):
    """A simple converter for the RESTfull URL routing system of Flask.

    .. code-block:: python

        @app.route('/<ObjectId:task_id>')
        def show_task(task_id):
            task = db.Task.get_from_id(task_id)
            return render_template('task.html', task=task)

    It checks the validate of the id and converts it into a
    :class:`bson.objectid.ObjectId` object. The converter will be
    automatically registered by the initialization of
    :class:`~flask.ext.mongokit.MongoKit` with keyword :attr:`ObjectId`.
    """

    def to_python(self, value):
        try:
            return bson.ObjectId(value)
        except bson.errors.InvalidId:
            raise abort(400)

    def to_url(self, value):
        return str(value)


class Document(Document):
    def get_or_404(self, id):
        """This method get one document over the _id field. If there no
        document with this id then it will raised a 404 error.

        :param id: The id from the document. The most time there will be
                   an :class:`bson.objectid.ObjectId`.
        """
        doc = self.get_from_id(id)
        if doc is None:
            abort(404)
        else:
            return doc

    def find_one_or_404(self, *args, **kwargs):
        """This method get one document over normal query parameter like
        :meth:`~flask.ext.mongokit.Document.find_one` but if there no document
        then it will raise a 404 error.
        """

        doc = self.find_one(*args, **kwargs)
        if doc is None:
            abort(404)
        else:
            return doc


class MongoKit(object):
    """This class is used to integrate `MongoKit`_ into a Flask application.

    :param app: The Flask application will be bound to this MongoKit instance.
                If an app is not provided at initialization time than it
                must be provided later by calling :meth:`init_app` manually.

    .. _MongoKit: http://namlook.github.com/mongokit/
    """

    def __init__(self, app=None):
        #: :class:`list` of :class:`mongokit.Document`
        #: which will be automated registed at connection
        self.registered_documents = []

        if app is not None:
            self.app = app
            self.init_app(self.app)
        else:
            self.app = None

    def init_app(self, app):
        """This method connect your ``app`` with this extension. Flask-
        MongoKit will now take care about to open and close the connection to 
        your MongoDB.
        
        Also it registers the
        :class:`flask.ext.mongokit.BSONObjectIdConverter`
        as a converter with the key word **ObjectId**.

        :param app: The Flask application will be bound to this MongoKit
                    instance.
        """
        app.config.setdefault('MONGODB_HOST', '127.0.0.1')
        app.config.setdefault('MONGODB_PORT', 27017)
        app.config.setdefault('MONGODB_DATABASE', 'flask')
        app.config.setdefault('MONGODB_USERNAME', None)
        app.config.setdefault('MONGODB_PASSWORD', None)
        app.config.setdefault('MONGODB_URL', 'mongodb://127.0.0.1:27071/')
        app.config.setdefault('MONGODB_CONNECTION_OPTIONS', {
            'auto_start_request': False
        })

        app.before_first_request(self._before_first_request)

        # 0.9 and later
        # no coverage check because there is everytime only one
        if hasattr(app, 'teardown_appcontext'):  # pragma: no cover
            app.teardown_appcontext(self._teardown_request)
        # 0.7 to 0.8
        elif hasattr(app, 'teardown_request'):  # pragma: no cover
            app.teardown_request(self._teardown_request)
        # Older Flask versions
        else:  # pragma: no cover
            app.after_request(self._teardown_request)

        # register extension with app only to say "I'm here"
        app.extensions = getattr(app, 'extensions', {})
        app.extensions['mongokit'] = self

        app.url_map.converters['ObjectId'] = BSONObjectIdConverter

        self.app = app

        self.mongokit_connection = Connection(
            host=app.config.get('MONGODB_HOST'),
            port=app.config.get('MONGODB_PORT'),
            **app.config.get('MONGODB_CONNECTION_OPTIONS', {})
        )
        if app.config.get('MONGODB_USERNAME') is not None:
            auth_success = self.mongokit_connection.authenticate(
                app.config.get('MONGODB_USERNAME'),
                app.config.get('MONGODB_PASSWORD')
            )
            if not auth_success:
                raise AuthenticationIncorrect('Server authentication failed')

    def register(self, documents):
        """Register one or more :class:`mongokit.Document` instances to the
        connection.

        Can be also used as a decorator on documents:

        .. code-block:: python

            db = MongoKit(app)

            @db.register
            class Task(Document):
                structure = {
                   'title': unicode,
                   'text': unicode,
                   'creation': datetime,
                }

        :param documents: A :class:`list` of :class:`mongokit.Document`.
        """
        self.mongokit_connection.register(documents)

    @property
    def connected(self):
        """Connection status to your MongoDB."""
        ctx = ctx_stack.top
        return getattr(ctx, 'mongokit_connection', None) is not None

    def disconnect(self):
        """Close the connection to your MongoDB."""
        if self.connected:
            ctx = ctx_stack.top
            ctx.mongokit_connection.disconnect()
            del ctx.mongokit_connection
            del ctx.mongokit_database

    def _before_first_request(self):
        self.mongokit_connection.start_request()

    def _teardown_request(self, response):
        self.mongokit_connection.end_request()
        return response

    def __getattr__(self, name, **kwargs):
        return getattr(self._get_mongo_database(), name)

    def __getitem__(self, name):
        return self._get_mongo_database()[name]

    def _get_mongo_database(self):
        ctx = ctx_stack.top
        return Database(self.mongokit_connection, ctx.app.config.get('MONGODB_DATABASE'))
