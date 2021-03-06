# -*- coding: utf-8 -*-
"""
    glia.views
    ~~~~~

    Implements views for Glia webapp

    :copyright: (c) 2013 by Vincent Ahrend.
"""
import datetime
import traceback

from flask import request, redirect, render_template, flash, url_for, session, \
    current_app, abort
from flask.ext.login import login_user, logout_user, current_user, login_required
from flask.ext.sqlalchemy import get_debug_queries
from jinja2.exceptions import TemplateNotFound
from uuid import uuid4
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import joinedload

from . import app, VIEW_CACHE_TIMEOUT
from .. import socketio
from forms import LoginForm, SignupForm, CreateMovementForm, CreateReplyForm, \
    DeleteThoughtForm, CreateThoughtForm, CreatePersonaForm, \
    EditThoughtForm, InviteMembersForm, EmailPrefsForm
# from glia.web.dev_helpers import http_auth
from glia.web.helpers import send_validation_email, \
    send_external_notifications, send_movement_invitation, \
    valid_redirect, make_view_cache_key, reorder, generate_graph
from nucleus.nucleus import ALLOWED_COLORS
from nucleus.nucleus.connections import db, cache
from nucleus.nucleus.helpers import process_attachments, recent_thoughts
from nucleus.nucleus.models import Persona, User, Movement, \
    Thought, Mindset, MovementMemberAssociation, Tag, TagPercept, \
    PerceptAssociation, Notification, \
    Mindspace, Blog, Dialogue, TextPercept

#
# UTILITIES
#


@app.before_request
def account_notifications():
    if not current_user.is_anonymous and not current_user.is_active:
        flash("Your account is not activated. Please click the link in the email that we sent you.")


@app.before_request
def mark_notifications_read():
    """Mark notifications for the current request path as read"""

    if not current_user.is_anonymous():
        notifications = Notification.query \
            .filter_by(url=request.path) \
            .filter_by(recipient=current_user.active_persona) \
            .filter_by(unread=True)

        for n in notifications:
            n.unread = False
            db.session.add(n)
            app.logger.debug("Marked {} read".format(n))

        db.session.commit()

#
# ROUTES
#


@app.route('/persona/<id>/activate')
# @http_auth.login_required
def activate_persona(id):
    """Activate a Persona and redirect to origin"""
    p = Persona.query.get_or_404(id)
    current_user.active_persona = p
    try:
        db.session.add(current_user)
        db.session.commit()
    except SQLAlchemyError, e:
        db.session.rollback()
        flash("There was an error activating your Persona. Please try again.")
        app.logger.error(
            "Error switching active persona on user {}\n{}".format(
                current_user, e))
    else:
        app.logger.info("{} activated {}".format(current_user, p))
    return redirect(request.referrer or url_for("web.index"))


@app.route('/persona/create', methods=["GET", "POST"])
@app.route('/movement/<for_movement>/create_persona', methods=["GET", "POST"])
# @http_auth.login_required
def create_persona(for_movement=None):
    """View for creating a new persona"""
    form = CreatePersonaForm()

    movement = None
    if for_movement:
        code = request.args.get("invitation_code", default=None)
        movement = Movement.query.get_or_404(for_movement)

    if form.validate_on_submit():
        created_dt = datetime.datetime.utcnow()
        persona = Persona(
            id=uuid4().hex,
            username=form.username.data,
            created=created_dt,
            modified=created_dt,
            color=form.color.data,
            user=current_user)

        # Create keypairs
        app.logger.info("Generating private keys for {}".format(persona))
        persona.generate_keys(form.password.data)

        # Create mindspace and blog
        persona.mindspace = Mindspace(
            id=uuid4().hex,
            author=persona)

        persona.blog = Blog(
            id=uuid4().hex,
            author=persona)

        db.session.add(persona)

        current_user.active_persona = persona
        db.session.add(current_user)

        notification = Notification(
            text="Welcome to RKTIK, {}!".format(persona.username),
            recipient=persona,
            source="system",
            url=url_for("web.persona", id=persona.id)
        )
        db.session.add(notification)

        if movement:
            persona.toggle_movement_membership(movement=movement,
                invitation_code=code)

        try:
            db.session.commit()
        except SQLAlchemyError, e:
            app.logger.error("Error creating new Persona: {}".format(e))
            db.session.rollback()
            flash("Sorry! There was an error creating your new Persona. Please try again.", "error")
        else:
            if movement:
                flash("Your new Persona {} is now a member of {}".format(persona.username, movement.username))
                app.logger.info("Created new Persona {} for user {} and joined {}.".format(
                    persona, current_user, movement))
                return redirect(url_for("web.movement_mindspace", id=movement.id))
            else:
                app.logger.info("Created new Persona {} for user {}.".format(persona, current_user))
                return redirect(url_for("web.persona", id=persona.id))
    return render_template('create_persona.html',
        form=form, movement=movement, movement_id=for_movement, allowed_colors=ALLOWED_COLORS.keys())


@app.route('/create', methods=["GET", "POST"])
@login_required
# @http_auth.login_required
def create_thought():
    """Post a new Thought"""

    form = CreateThoughtForm()
    ms = None
    parent = None
    thought_data = None

    # Prepopulate form if redirected here from chat
    if not form.longform.raw_data and "text" in request.args:
        form.longform.data = request.args.get("text")

    if "parent" in request.args and request.args['parent'] is not None:
        form.parent.data = request.args['parent']
    parent = Thought.query.get_or_404(form.parent.data) if form.parent.data else None

    if request.args.get("mindset"):
        form.mindset.data = request.args['mindset']
    elif parent is not None:
        ms = parent.mindset
    else:
        flash("New thoughts needs either a parent or a mindset to live in.")
        app.logger.error("Neither parent nor mindset given {}")

    ms = Mindset.query.get_or_404(form.mindset.data) if form.mindset.data else None

    if form.validate_on_submit():
        try:
            thought_data = Thought.create_from_input(
                text=form.text.data,
                longform=form.longform.data,
                longform_source=form.lfsource.data,
                parent=parent,
                mindset=ms)
        except ValueError, e:
            flash("There was an error creating your thought ({})".format(e))
            app.logger.error("Error creating new thought ({})".format(e))

        if thought_data is not None:
            thought = thought_data["instance"]
            thought.posted_from = "web-form"

            thought.toggle_upvote()

            db.session.add(thought)
            db.session.add_all(thought_data["notifications"])

            try:
                db.session.commit()
            except SQLAlchemyError, e:
                db.session.rollback()
                app.logger.error("Error creating longform thought: {}".format(e))
                flash("An error occured saving your message. Please try again.")
            else:
                map(send_external_notifications, thought_data["notifications"])

                # Render using templates
                thought_macros_template = current_app.jinja_env.get_template(
                    'macros/thought.html')
                thought_macros = thought_macros_template.make_module(
                    {'request': request})

                data = {
                    'username': thought.author.username,
                    'msg': render_template("chatline.html", thought=thought),
                    'thought_id': thought.id,
                    'parent_id': thought.parent_id,
                    'parent_short': thought_macros.short(thought.parent) if thought.parent else None,
                    'vote_count': thought.upvote_count()
                }
                socketio.emit('message', data, room=form.mindset.data)

                socketio.emit('comment', {'msg': thought_macros.comment(thought),
                    'parent_id': form.parent.data}, room=form.parent.data)
                flash("Great success! Your new post is ready.")
                return redirect(url_for("web.thought", id=thought.id))

    return render_template("create_thought.html",
        form=form, mindset=ms, parent=parent)


@app.route('/thought/<id>/delete', methods=["GET", "POST"])
@login_required
# @http_auth.login_required
def delete_thought(id=None):
    thought = Thought.query.get_or_404(id)
    form = DeleteThoughtForm()

    if not thought.authorize("delete", current_user.active_persona.id):
        flash("You are not allowed to change {}'s Thoughts".format(thought.author.username))
        app.logger.error("Tried to change visibility of {}'s Thoughts".format(thought.author))
        return redirect(request.referrer or url_for('.index'))

    if form.validate_on_submit():
        if thought.state == -2:
            thought.set_state(0)
            if thought.parent is not None:
                thought.parent.update_comment_count(1)
        else:
            thought.set_state(-2)
            if thought.parent is not None:
                thought.parent.update_comment_count(-1)

        try:
            db.session.add(thought)
            db.session.commit()
        except:
            app.logger.error("Error setting publish state of {}\n{}".format(thought, traceback.format_exc()))
            db.session.rollback()
        else:
            flash("Updated visibility of {}".format(thought))

            app.logger.info("Thought {} set to publish state {}".format(id, thought.state))
            return(redirect(url_for(".thought", id=thought.id)))

    return render_template("delete_thought.html", thought=thought, form=form)


@app.route('/thought/<id>/edit', methods=["GET", "POST"])
@login_required
# @http_auth.login_required
def edit_thought(id=None):
    thought = Thought.query.get_or_404(id)
    form = EditThoughtForm()

    if not thought.authorize("update", current_user.active_persona.id):
        flash("You are not allowed to change {}'s Thoughts".format(thought.author.username))
        app.logger.error("Tried to edit {}'s Thoughts".format(thought.author))
        return redirect(request.referrer or url_for('web.index'))

    attachments = thought.attachments

    if form.validate_on_submit():
        thought.text = form.text.data
        db.session.add(thought)

        # Append new attachments from longform field
        if form.longform.data and len(form.longform.data) > 0:
            lftext, percepts = process_attachments(form.longform.data)
            app.logger.debug("Extracted {} percepts from longform".format(len(percepts)))

            lftext_percept = TextPercept.get_or_create(lftext,
                source=form.lfsource.data)
            percepts.add(lftext_percept)

            for p in percepts:
                if PerceptAssociation.query.filter_by(thought=thought) \
                        .filter_by(percept=p).count() == 0:
                    pa = PerceptAssociation(thought=thought, percept=p,
                        author=current_user.active_persona)
                    db.session.add(pa)

        # Update longform fields
        edited_lf = [(k[9:], v) for k, v in request.form.items() if k.startswith('longform-')]
        for key, lftext in edited_lf:
            oldp = TextPercept.query.get(key)
            newp = TextPercept.get_or_create(lftext, source=request.form.get('lfsource-' + key))
            if oldp != newp:
                app.logger.info("Changed attachment from {} to {}".format(oldp, newp))
                pa = PerceptAssociation.query.filter_by(
                    thought=thought).filter_by(percept=oldp).first()
                pa.percept = newp
                pa.source = request.form.get('lfsource-' + key)
                db.session.add(pa)

        # Delete attachments
        for delete_id in request.form.getlist('delete'):
            app.logger.info("Removing percept {}".format(delete_id))
            PerceptAssociation.query.filter_by(thought=thought) \
                .filter_by(percept_id=delete_id).delete()

        # Write to database
        try:
            db.session.commit()
        except:
            app.logger.error("Error setting publish state of {}\n{}".format(thought, traceback.format_exc()))
            db.session.rollback()
        else:
            flash("Updated {}".format(thought))

            app.logger.info("Thought {} updated".format(id))
            return(redirect(url_for("web.thought", id=thought.id)))

    return render_template("edit_thought.html", thought=thought, form=form,
        attachments=attachments)


@app.route('/help/<page>', methods=["GET"])
def help(page):
    """Handler for help pages"""
    try:
        rv = render_template("help_{}.html".format(page))
    except TemplateNotFound:
        app.logger.warning("Request for unavailable help page: '{}'".format(page))
        abort(404)
    else:
        return rv


@app.route('/', methods=["GET"])
# @http_auth.login_required
# @cache.cached(
#     timeout=VIEW_CACHE_TIMEOUT,
#     key_prefix=make_view_cache_key
# )
def index():
    """Front page"""
    movementform = CreateMovementForm()

    # Determine content source
    if current_user.is_anonymous():
        more_movements = Movement.query \
            .filter(Movement.id.in_([m['id'] for m in Movement.top_movements()]))

        top_main = reorder(Thought.query.filter(Thought.id.in_(
            Thought.top_thought())))

        top_global = None
        graph_json = generate_graph()
    else:
        more_movements = Movement.query \
            .filter(Movement.id.in_(
                current_user.active_persona.suggested_movements()))

        top_main = reorder(Thought.query.filter(
            Thought.id.in_(
                Thought.top_thought(persona=current_user.active_persona,
                    filter_blogged=True))
        ).options(joinedload('author').joinedload('percept_assocs')))

        top_global = reorder(Thought.query.filter(Thought.id.in_(
            Thought.top_thought())))

        graph_json = generate_graph(persona=current_user.active_persona)

    recent = Thought.query.filter(Thought.id.in_(recent_thoughts())) \
        .order_by(Thought.created.desc()).all()

    return render_template('index.html', movementform=movementform,
        top_main=top_main, top_global=top_global, recent_thoughts=recent,
        more_movements=more_movements, graph_json=graph_json)


@app.route('/movement/<movement_id>/invite', methods=["GET", "POST"])
@login_required
# @http_auth.login_required
def invite_members(movement_id):
    """Let movments invite members by username or email adress"""
    movement = Movement.query.get_or_404(movement_id)
    invited = list()
    invitation_code = None

    form = InviteMembersForm()
    if form.validate_on_submit():
        for handle in form.handles:
            if send_movement_invitation(handle, movement, personal_message=form.message):
                app.logger.info("Invited {} to {}".format(handle, movement))
                invited.append(handle)
            else:
                flash("There was an error sending an invitation to {}. Please try again.".format(
                    handle), 'error')

    mma = MovementMemberAssociation(
        movement=movement,
        role="invited",
        active=False,
        invitation_code=uuid4().hex)
    db.session.add(mma)
    try:
        db.session.commit()
    except SQLAlchemyError, e:
        app.logger.exception("Error generating invitation code: {}".format(e))
    else:
        invitation_code = mma.invitation_code

    return render_template("movement_invite.html",
        form=form, movement=movement, invited=invited, invitation_code=invitation_code)


@app.route('/login', methods=["GET", "POST"])
# @http_auth.login_required
def login():
    """Login a user"""
    if not current_user.is_anonymous() and current_user.is_authenticated():
        return redirect(url_for("web.index"))

    form = LoginForm()
    if form.validate_on_submit():
        form.user.authenticated = True
        db.session.add(form.user)
        db.session.commit()
        if not form.user.active:
            flash("Please click the link in the validation email we sent you to activate your account.")
        else:
            login_user(form.user, remember=True)
            session["active_persona"] = form.user.active_persona.id
            app.logger.debug("User {} logged in with {}.".format(current_user, current_user.active_persona))
        return form.redirect(valid_redirect(request.args.get('next'))or url_for('web.index'))
    form_action = url_for('web.login', next=valid_redirect(request.args.get('next')))
    return render_template('login.html', form=form, form_action=form_action)


@app.route('/logout', methods=["GET", "POST"])
@login_required
# @http_auth.login_required
def logout():
    """Logout a user"""
    user = current_user
    app.logger.debug("{} logging out.".format(user))
    user.authenticated = False
    db.session.add(user)
    db.session.commit()
    logout_user()
    session["active_persona"] = None
    return redirect(url_for('web.login'))


@app.route('/movement/<id>/')
# @http_auth.login_required
def movement(id):
    """Redirect user depending on whether he is a member or not"""
    movement = Movement.query.get_or_404(id)
    if not current_user.is_anonymous() and movement.current_role() in ["member", "admin"]:
        rv = redirect(url_for("web.movement_mindspace", id=id))
    else:
        code = request.args.get('invitation_code', default=None)
        rv = redirect(url_for("web.movement_blog", id=id, invitation_code=code))
    return rv


@app.route('/movement/<id>/blog/', methods=["GET"])
@app.route('/movement/<id>/blog/page-<int:page>/', methods=["GET"])
# @http_auth.login_required
# @cache.cached(
#     timeout=VIEW_CACHE_TIMEOUT,
#     key_prefix=make_view_cache_key
# )
def movement_blog(id, page=1):
    """Display a movement's profile"""
    movement = Movement.query.get_or_404(id)

    thought_selection = movement.blog.index \
        .filter_by(author_id=movement.id) \
        .filter(Thought.state >= 0) \
        .order_by(Thought.created.desc()) \
        .paginate(page, 5)

    code = request.args.get("invitation_code", default=None)
    return render_template('movement_blog.html', movement=movement,
        thoughts=thought_selection, code=code)


@app.route("/movements/")
def movement_list():
    """Display a list of all available movements"""
    movements = Movement.query.order_by(Movement.username).all()

    return render_template("movement_list.html", movements=movements)


@app.route('/movement/<id>/mindspace', methods=["GET"])
# @http_auth.login_required
def movement_mindspace(id):
    """Display a movement's profile"""
    movement = Movement.query.get(id)
    if not movement:
        flash("Movement not found")
        app.logger.warning("Movement '{}' not found. User: {}".format(
            id, current_user))
        return(redirect(url_for('.movements')))

    if movement.private and not movement.authorize("read", current_user.active_persona.id):
        flash("Only members can access the mindspace of '{}'".format(movement.username))
        return redirect(url_for("web.movement_blog", id=movement.id))

    thought_selection = reorder(Thought.query
        .filter(Thought.id.in_(movement.mindspace_top_thought())))
    top_posts = list()

    blog_index = [t.id for t in movement.blog.index]
    for candidate in thought_selection:
        candidate.promote_target = None if candidate.id in blog_index \
            else movement
        if candidate.upvote_count() > 0:
            top_posts.append(candidate)

    member_selection = MovementMemberAssociation.query \
        .filter_by(movement=movement) \
        .filter_by(active=True) \
        .order_by(MovementMemberAssociation.last_seen.desc()) \
        .limit(10)

    return render_template('movement_mindspace.html',
        movement=movement, thoughts=top_posts,
        member_selection=member_selection)


@app.route('/movement/', methods=["GET", "POST"])
@login_required
# @http_auth.login_required
def movements(id=None):
    """Create movements"""
    form = CreateMovementForm(id=id)

    # Create a movement
    if form.validate_on_submit():
        movement_id = uuid4().hex
        movement_created = datetime.datetime.utcnow()
        movement = Movement(
            id=movement_id,
            username=form.name.data,
            description=form.mission.data,
            admin=current_user.active_persona,
            created=movement_created,
            modified=movement_created,
            color=form.color.data,
            private=form.private.data)
        current_user.active_persona.toggle_movement_membership(movement=movement, role="admin")
        try:
            db.session.add(movement)
            db.session.commit()
        except Exception, e:
            app.logger.exception("Error creating movement: {}".format(e))
            flash("There was a problem creating your movement. Please try again.")
        else:
            app.logger.debug("{} created new movement {}".format(current_user.active_persona, movement))
            return redirect(url_for('.movement', id=movement_id))

    return render_template("movements.html", form=form, allowed_colors=ALLOWED_COLORS.keys())


@app.route('/notebook', methods=["GET"])
@login_required
def notebook():
    chat = current_user.active_persona.mindspace
    conversations = current_user.active_persona.conversation_list()
    marked_thoughts = chat.index.filter(Thought._upvotes > 0).order_by(Thought.created.desc())
    return render_template("notebook.html", chat=chat,
        conversations=conversations, marked_thoughts=marked_thoughts)


@app.route('/notifications', methods=["GET", "POST"])
@app.route('/notifications/page-<page>', methods=["GET", "POST"])
@login_required
# @http_auth.login_required
def notifications(page=1):
    notifications = current_user.active_persona \
        .notifications \
        .order_by(Notification.modified.desc()) \
        .paginate(page, 25)

    form = EmailPrefsForm(obj=current_user)
    if form.validate_on_submit():
        current_user.email_react_private = form.data['email_react_private']
        current_user.email_react_reply = form.data['email_react_reply']
        current_user.email_react_mention = form.data['email_react_mention']
        current_user.email_react_follow = form.data['email_react_follow']
        current_user.email_system_security = form.data['email_system_security']
        current_user.email_system_features = form.data['email_system_features']
        current_user.email_catchall = form.data['email_catchall']

        try:
            db.session.add(current_user)
            db.session.commit()
        except SQLAlchemyError:
            app.logger.exception("Error saving email prefs")
            flash("Error updating email preferences. Please try again.")
        else:
            flash("Email preferences updated")

    catchall = True if current_user.email_catchall else False

    return(render_template('notifications.html',
        notifications=notifications, form=form, catchall=catchall))


@app.route('/persona/<id>/')
# @http_auth.login_required
def persona(id):
    persona = Persona.query.get_or_404(id)
    convs = None
    followed = None

    cp = current_user.active_persona

    if current_user.is_anonymous():
        chat = None
    elif persona == cp:
        chat = None
        convs = cp.conversation_list()
        followed = cp.blogs_followed
    else:
        chat = Dialogue.get_chat(persona, cp)
        if inspect(chat).persistent is False:
            app.logger.info('Storing {} in database'.format(chat))
            # chat object is newly created
            db.session.add(chat)
            try:
                db.session.commit()
            except SQLAlchemyError, e:
                db.session.rollback()
                flash("There was an error starting a dialogue with {}.".format(
                    persona.username))

                app.logger.error(
                    "Error creating dialogue between {} and {}\n{}".format(
                        cp, persona, e))
                chat = None

    movements = MovementMemberAssociation.query \
        .filter_by(active=True) \
        .filter_by(persona_id=persona.id) \
        .all()

    return(render_template('persona.html', chat=chat, persona=persona,
        movements=movements, conversations=convs, followed=followed))


@app.route('/anonymous/blog/', methods=["GET"])
@app.route('/persona/<id>/blog/', methods=["GET"])
@app.route('/persona/<id>/blog/page-<int:page>/', methods=["GET"])
# @http_auth.login_required
# @cache.cached(
#     timeout=VIEW_CACHE_TIMEOUT,
#     key_prefix=make_view_cache_key
# )
def persona_blog(id, page=1):
    """Display a persona's blog"""
    if id is None:
        return redirect(url_for('web.signup'))

    p = Persona.query.get_or_404(id)

    thought_selection = p.blog.index \
        .filter_by(author_id=p.id) \
        .filter(Thought.state >= 0) \
        .order_by(Thought.created.desc()) \
        .paginate(page, 5)

    return render_template('persona_blog.html', persona=p, thoughts=thought_selection)


@app.route('/signup', methods=["GET", "POST"])
# @http_auth.login_required
def signup():
    """Signup a new user"""
    from uuid import uuid4
    form = SignupForm()
    mma = None

    invitation_code = request.args.get('invitation_code', default=None)
    if invitation_code:
        mma = MovementMemberAssociation.query.filter_by(invitation_code=invitation_code).first()
        if mma is None:
            flash("Can not find the movement you were invited to", "error")

    if form.validate_on_submit():
        created_dt = datetime.datetime.utcnow()
        persona = Persona(
            id=uuid4().hex,
            username=form.username.data,
            created=created_dt,
            modified=created_dt,
            color=form.color.data)

        # Create keypairs
        app.logger.info("Generating private keys for {}".format(persona))
        persona.generate_keys(form.password.data)

        # Create mindspace and blog
        persona.mindspace = Mindspace(
            id=uuid4().hex,
            author=persona)

        persona.blog = Blog(
            id=uuid4().hex,
            author=persona)

        db.session.add(persona)

        # Activate invitation
        if mma and not mma.active:
            mma.persona = persona
            mma.active = True
            mma.role = "member"
            db.session.add(mma)

        # Auto-follow top movements
        top_movements = Movement.top_movements()
        app.logger.debug("Auto joining {}".format(
            ", ".join([m["username"] for m in top_movements])))
        for m_data in top_movements:
            m = Movement.query.get(m_data["id"])
            persona.toggle_following(m)
        cache.delete_memoized(persona.suggested_movements)

        notification = Notification(
            text="Welcome to RKTIK, {}!".format(persona.username),
            recipient=persona,
            url="http://www.rktik.com/movement/27fe161d2ba64f4bb4986a99bebea18a/mindspace",
            source="system"
        )
        db.session.add(notification)

        created_dt = datetime.datetime.utcnow()
        user = User(
            id=uuid4().hex,
            email=form.email.data,
            active_persona=persona,
            created=created_dt,
            modified=created_dt)
        user.set_password(form.password.data)
        db.session.add(user)

        persona.user = user
        try:
            db.session.commit()
        except IntegrityError, e:
            app.logger.error("Error during signup: {}".format(e))
            db.session.rollback()
            flash("Sorry! There was an error creating your account. Please try again.", "error")
            return render_template('signup.html', form=form)
        else:
            send_validation_email(user, db)
            login_user(user, remember=True)

            flash("Welcome to RKTIK! Click the link in the activation email we just sent you to be able to reset your account when you lose your password.".format(form.username.data))
            app.logger.debug("Created new account {} with active Persona {}.".format(user, persona))

        rv = url_for('web.index') if mma is None else url_for('web.movement', id=mma.movement.id)
        if valid_redirect(request.args.get('next')):
            rv = valid_redirect(request.args.get('next'))
        return redirect(rv)

    if request.method == "GET":
        if not current_user.is_anonymous():
            if mma:
                if mma.active:
                    flash("This activation code has been used before. You can try joining the movement by clicking the join button below.")
                else:
                    flash("You were invited to join this movement. Click the \"Join movement\" button to do so.")
                return redirect(url_for('web.movement', id=mma.movement.id, invitation_code=invitation_code))
            else:
                return redirect(url_for("web.index"))

    kwargs = dict()
    if mma:
        kwargs["invitation_code"] = mma.invitation_code

    if valid_redirect(request.args.get('next')):
        kwargs['next'] = valid_redirect(request.args.get('next'))

    form_url = url_for('web.signup', **kwargs)

    return render_template('signup.html',
        form=form, form_url=form_url, allowed_colors=ALLOWED_COLORS.keys(),
        mma=mma)


@app.route('/validate/<id>/<signup_code>', methods=["GET"])
# @http_auth.login_required
def signup_validation(id, signup_code):
    """Validate a user's email adress"""

    user = User.query.get(id)

    if user is None:
        flash("This signup link is invalid.")

    elif user.validated:
        flash("Your email address is already validated. You're good to go.")

    elif not user.valid_signup_code(signup_code):
        app.logger.error("User {} tried validating with invalid signup code {}.".format(user, signup_code))
        send_validation_email(user, db)
        flash("Oops! Invalid signup code. We have sent you another confirmation email. Please try clicking the link in that new email. ", "error")
    else:
        login_user(user, remember=False)
        session["active_persona"] = user.active_persona.id
        user.validate()
        db.session.add(user)
        db.session.commit()
        app.logger.info("{} validated their email address.".format(user))
        flash("Your email address is now verified.")
    return redirect(url_for('.index'))


@app.route('/tag/<name>/')
# @http_auth.login_required
def tag(name):
    tag = Tag.query.filter_by(name=name).first()

    thoughts = Thought.query.join(PerceptAssociation).join(TagPercept).filter(TagPercept.tag_id == tag.id)

    return render_template("tag.html", tag=tag, thoughts=thoughts)


@app.route('/thought/<id>/')
# @http_auth.login_required
def thought(id=None):
    thought = Thought.query.get_or_404(id)

    if not thought.authorize("read", current_user.active_persona.id):
        flash("This Thought is private")
        return(redirect(url_for("web.index")))

    # Load conversation context
    context = []
    while(len(context) < thought.context_length) and thought.parent is not None:
        context.append(thought.parent if len(context) == 0 else context[-1].parent)
        if context[-1].parent is None:
            break
    context = context[::-1]  # reverse list

    if thought.state < 0 and not thought.authorize("delete", current_user.active_persona.id):
        flash("This Thought is currently unavailable.")
        if request.referrer and request.referrer != request.url:
            redirect_target = request.referrer
        else:
            redirect_target = url_for('web.index')
        return redirect(redirect_target)

    reply_form = CreateReplyForm(parent=thought.id)

    return render_template("thought.html", thought=thought, context=context,
        reply_form=reply_form)
