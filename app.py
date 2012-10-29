import datetime

from flask import abort, Flask, request, flash, g, redirect, render_template, url_for, session
from flask.ext.wtf import Form, TextField as WTFTextField, Required, Email
from flask.ext.sqlalchemy import SQLAlchemy
from flask.ext.couchdb import BooleanField, CouchDBManager, DateTimeField, Document, TextField, ViewDefinition, ViewField
from gevent.wsgi import WSGIServer
from werkzeug.local import LocalProxy
from werkzeug.contrib.cache import SimpleCache

""" Config """
DATABASE = '/tmp/khemia.db'
DEBUG = True
# TODO: Generate after installation, keep secret.
SECRET_KEY = '\xae\xac\xde\nIH\xe4\xed\xf0\xc1\xb9\xec\x08\xf6uT\xbb\xb6\x8f\x1fOBi\x13'
PASSWORD_HASH = None
SQLALCHEMY_DATABASE_URI = 'sqlite:////tmp/khemia.db'
SERVER_NAME = 'app.soma:5000'

COUCHDB_SERVER = 'http://app.soma:5984'
COUCHDB_DATABASE = 'ark'

app = Flask(__name__)
app.config.from_object(__name__)
db = SQLAlchemy(app)


# Setup CouchDB
manager = CouchDBManager()


# Setup Document Types
class Persona(Document):
    doc_type = "persona"

    username = TextField()
    email = TextField()
    private = TextField()
    public = TextField()
    created = DateTimeField(default=datetime.datetime.now)


class Star(Document):
    doc_type = 'star'

    text = TextField()
    creator_id = TextField()
    created = DateTimeField(default=datetime.datetime.now)


# Setup View Definitions
controlled_personas_view = ViewDefinition('soma', 'controlled_personas', '''\
        function (doc) {
            if (doc.doc_type == 'persona' && doc.private != "") {
                emit(doc.username, doc);
            }
        }
    ''')
manager.add_viewdef(controlled_personas_view)

starmap_view = ViewDefinition('soma', 'starmap', '''\
    function (doc) {
        if (doc.doc_type == 'star') {
            emit(doc.creator_id, doc);
        }
    }''')
manager.add_viewdef(starmap_view)

sternenhimmel_view = ViewDefinition('soma', 'sternenhimmel', '''\
    function (doc) {
        if (doc.doc_type == 'star') {
            emit(doc.created, doc);
        }
    }''')
manager.add_viewdef(sternenhimmel_view)

manager.setup(app)

# Allows access of 'g.couch' through 'couch'
couch = LocalProxy(lambda: g.couch)

# Setup Cache
cache = SimpleCache()


""" DB code """


def get_active_persona():
    """ Return the currently active persona or 0 if there is no controlled persona. """

    if session['active_persona'] is None:
        controlled_personas = controlled_personas_view()

        if len(controlled_personas) == 0:
            return "0"
        else:
            session['active_persona'] = controlled_personas.rows[0].value['_id']

    return session['active_persona']


def logged_in():
    return cache.get('password') is not None


@app.context_processor
def persona_context():
    return dict(controlled_personas=controlled_personas_view().rows)


@app.before_request
def before_request():
    # TODO: serve favicon.ico
    if request.base_url[-3:] == "ico":
        abort(404)

    setup_url = "/".join(["http:/", app.config['SERVER_NAME'], "setup"])
    login_url = "/".join(["http:/", app.config['SERVER_NAME'], "login"])

    session['active_persona'] = get_active_persona()

    if app.config['PASSWORD_HASH'] == None and request.base_url != setup_url:
        app.logger.info("Redirecting to Setup")
        return redirect(url_for('setup', _external=True))

    if request.base_url not in [setup_url, login_url] and not logged_in():
        app.logger.info("Redirecting to Login")
        return redirect(url_for('login', _external=True))


@app.teardown_request
def teardown_request(exception):
    pass

""" Views """


@app.route('/login', methods=['GET', 'POST'])
def login():
    """Display a login form and create a session if the correct pw is submitted"""
    from Crypto.Protocol.KDF import PBKDF2
    from hashlib import sha256

    error = None
    if request.method == 'POST':
        # TODO: Is this a good idea?
        salt = app.config['SECRET_KEY']
        pw_submitted = PBKDF2(request.form['password'], salt)

        if sha256(pw_submitted).hexdigest() != app.config['PASSWORD_HASH']:
            error = 'Invalid password'
        else:
            cache.set('password', pw_submitted)
            flash('You are now logged in')
            return redirect(url_for('universe'))
    return render_template('login.html', error=error)


@app.route('/logout')
def logout():
    cache.set('password', None)
    flash('You were logged out')
    return redirect(url_for('login'))


@app.route('/setup', methods=['GET', 'POST'])
def setup():
    from Crypto.Protocol.KDF import PBKDF2
    from hashlib import sha256

    error = None
    if request.method == 'POST':
        logged_in()
        if request.form['password'] is None:
            error = 'Please enter a password'
        else:
            salt = app.config['SECRET_KEY']
            password = PBKDF2(request.form['password'], salt)
            app.config['PASSWORD_HASH'] = sha256(password).hexdigest()
            cache.set('password', password)
            return redirect(url_for('universe'))
    return render_template('setup.html', error=error)


@app.route('/')
def universe():
    """ Render the landing page """
    # Redirect to >new persona< if no persona is found
    if session['active_persona'] == '0':
        return redirect(url_for('create_persona'))

    sternenhimmel = sternenhimmel_view().rows

    return render_template('universe.html', sternenhimmel=sternenhimmel)


@app.route('/p/<id>/')
def persona(id):
    """ Render home of a persona """
    persona = Persona.load(id)
    if persona is None:
        abort(404)

    starmap = starmap_view[id].rows

    return render_template('persona.html', persona=persona, starmap=starmap)


class Create_persona_form(Form):
    """ Generate form for creating a persona """
    name = WTFTextField('Name', validators=[Required(), ])
    email = WTFTextField('Email (optional)', validators=[Email(), ])


def encrypt_symmetric(data, password):
    """ Encrypt data using AES algorithm """

    from Crypto.Cipher import AES
    from Crypto.Random import get_random_bytes
    from Padding import appendPadding as append_padding

    iv = get_random_bytes(16)
    encoder = AES.new(password, AES.MODE_CBC, iv)
    data = append_padding(data)

    # 16 byte IV is prepended to the encrypted data
    return "".join([iv, encoder.encrypt(data)])


def decrypt_symmetric(data, password):
    """ Decrypt data using AES algorithm """

    from Crypto.Cipher import AES
    from Padding import removePadding as remove_padding

    iv = data[:16]
    decoder = AES.new(password, AES.MODE_CBC, iv)
    data = decoder.decrypt(data[16:])

    return remove_padding(data)


@app.route('/p/create', methods=['GET', 'POST'])
def create_persona():
    """ Render page for creating new persona """
    from uuid import uuid4
    from Crypto.PublicKey import RSA
    from base64 import b64encode

    form = Create_persona_form()
    if form.validate_on_submit():
        # This is a unique ID which identifies the persona across all contexts
        uuid = uuid4().hex

        # This is the RSA key used to sign the new persona's actions
        key = RSA.generate(2048)

        # Encrypt private key before saving to DB/disk
        key_private = encrypt_symmetric(key.exportKey(), cache.get('password'))
        key_public = encrypt_symmetric(key.publickey().exportKey(), cache.get('password'))

        # Save persona to DB
        p = Persona(
                id=uuid,
                active=False,
                username=request.form['name'],
                email=request.form['email'],
                private=b64encode(key_private),
                public=b64encode(key_public))
        p.store()

        flash("New persona {} created!".format(p.username))
        return redirect(url_for('persona', id=uuid))

    return render_template('create_persona.html',
        form=form,
        next=url_for('create_persona'))


class Create_star_form(Form):
    """ Generate form for creating a star """
    text = WTFTextField('Content', validators=[Required(), ])


@app.route('/s/create', methods=['GET', 'POST'])
def create_star():
    from uuid import uuid4
    """ Create a new star """

    # TODO: Allow selection of author persona
    if session['active_persona'] == '0':
        abort(404)
    creator = Persona.load(session['active_persona'])

    form = Create_star_form()
    if form.validate_on_submit():
        app.logger.info('Creating new star')
        uuid = uuid4().hex

        new_star = Star(id=uuid, text=request.form['text'], creator_id=creator.id)
        new_star.store()

        flash('New star created!')
        return redirect(url_for('star', id=uuid))
    return render_template('create_star.html', form=form, creator=creator)


@app.route('/s/<id>/', methods=['GET'])
def star(id):
    """ Display a single star """
    star = Star.load(id)
    creator = Persona.load(star.creator_id)

    return render_template('star.html', star=star, creator=creator)


if __name__ == '__main__':

    # flask development server
    app.run()

    # gevent server
    #local_server = WSGIServer(('', 12345), app)
    #local_server.serve_forever()
