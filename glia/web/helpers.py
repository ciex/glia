import logging
import os
import pytz
import sendgrid

from flask import render_template, request
from flask.ext.login import current_user
from hashlib import sha256
from uuid import uuid4
from sendgrid import SendGridClient, SendGridClientError, SendGridServerError
from sqlalchemy.exc import SQLAlchemyError

from nucleus.nucleus.models import Persona, Movement, MovementMemberAssociation

from .. import socketio


logger = logging.getLogger('web')


class UnauthorizedError(Exception):
    """Current user is not authorized for this action"""
    pass


def authorize_filter(obj, action, actor=None):
    """Return True if action on obj is authorized for active Persona or
    given Persona

    Args:
        obj (nucleus.models.Serializable): Implements the authorize method
        action (String): One of the actions defined in Nucleus
        actor (Identity): Optional identity to check for

    Returns:
        Boolean: True if action is currently authorized
    """
    if actor is None:
        actor = current_user.active_persona

    return obj.authorize(action, actor.id)


def localtime(value, tzval="UTC"):
    """Convert tz-naive UTC datetime into tz-naive local datetime

    Args:
        value (datetime): timezone naive UTC datetime
        tz (sting): timezone e.g. 'Europe/Berlin' (see pytz references)
    """
    value = value.replace(tzinfo=pytz.utc)  # assuming value is utc time
    value = value.astimezone(pytz.timezone(tzval))  # convert to local time (tz-aware)
    value = value.replace(tzinfo=None)  # make tz-naive again
    return value


def make_view_cache_key(*args, **kwargs):
    """Make a cache key for view function depending on logged in user and path

    Returns:
        string: Cache key for use by Flask-Cache
    """
    persona = current_user.active_persona.id if not current_user.is_anonymous() else "anon"
    url = request.url
    rv = "-".join([persona, url]).encode('utf-8')
    return sha256(rv).hexdigest()


def send_email(message):
    """Send Email using Sendgrid service

    Args:
        message (Sendgrid Message): Readily configured message object

    Raises:
        SendGridClientError
        SendGridServerError
    """
    from flask import current_app

    sg_user = os.environ.get('SENDGRID_USERNAME') or current_app.config["SENDGRID_USERNAME"]
    sg_pass = os.environ.get('SENDGRID_PASSWORD') or current_app.config["SENDGRID_PASSWORD"]
    sg = SendGridClient(sg_user, sg_pass, raise_errors=True)
    return sg.send(message)


def send_external_notifications(notification):
    """Send Email and trigger Desktop notifications depending on user prefs

    Args:
        notification (Notification): Notification object specifying message
            recipient etc.
    """

    # Desktop notifications
    if isinstance(notification.recipient, Persona):
        data = {
            'title': notification.source,
            'msg': notification.text
        }
        socketio.emit('message', data,
            room=notification.recipient.id, namespace="/personas")

    # Email notification
    if isinstance(notification.recipient, Persona):
        if notification.email_pref and getattr(notification.recipient.user,
            notification.email_pref) is True \
                and not notification.recipient.user.email_catchall:

            message = sendgrid.Mail()
            message.add_to("{} <{}>".format(
                notification.recipient.username, notification.recipient.user.email))
            message.set_subject(notification.text)
            message.set_html(render_template("email/notification.html",
                notification=notification))
            message.set_from('RKTIK Notifications')

            logger.info("Sending email notification to {}: {}".format(
                notification.recipient, notification.recipient.user.email))

            try:
                status, msg = send_email(message)
            except SendGridClientError, e:
                logger.error("Client error sending notification email: {}".format(e))
            except SendGridServerError, e:
                logger.error("Server error sending notification email: {}".format(e))
        else:
            logger.info("{} not sent because of user preference '{}'".format(
                notification, notification.email_pref))


def send_movement_invitation(recipient, movement, personal_message=None):
    """Send an email invitation to a user, asking them to join a movement

    Args:
        recipient (String): Recipient email address
        movement (Movement): Movement to which the recipient will be invited
        message (String): Optional personal message from the inviter
    """
    from nucleus.nucleus.database import db

    mma = MovementMemberAssociation(
        movement=movement,
        role="invited",
        active=False,
        invitation_code=uuid4().hex)

    db.session.add(mma)

    if not isinstance(movement, Movement):
        raise ValueError("{} is not a valid movement instance".format(
            movement))

    message = sendgrid.Mail()
    message.add_to(recipient)
    message.set_subject("You were invited to join the {} movement".format(
        movement.username))
    message.set_html(render_template("email/movement_invitation.html",
        movement=movement,
        sender=current_user.active_persona,
        personal_message=personal_message,
        invitation_code=mma.invitation_code))
    message.set_from('RKTIK {} movement'.format(movement.username))

    try:
        db.session.commit()
        status, msg = send_email(message)
    except (SendGridClientError, SendGridServerError), e:
        logger.error("Error sending email invitation to '{}' code '{}': {}".format(
            recipient, mma.invitation_code, e))
    except SQLAlchemyError, e:
        logger.error("Error sending email invitation to '{}' code '{}': {}".format(
            recipient, mma.invitation_code, e))
    else:
        logger.info("Sent invitation email for {} to '{}'".format(
            movement, recipient))
        return mma


def send_validation_email(user, db):
    """Send validation email using sendgrid, resetting the signup code.

    Args:
        user (User): Nucleus user object
        db (SQLAlchemy): Database used to store user's new signup code

    Throws:
        ValueError: If active user has no name or email address
    """
    from nucleus.nucleus.database import db
    from flask import current_app

    user.signup_code = uuid4().hex
    db.session.add(user)
    db.session.commit()

    name = user.active_persona.username
    email = user.email

    if name is None or email is None:
        raise ValueError("Username and email can't be empty")

    message = sendgrid.Mail()
    message.add_to("{} <{}>".format(name, email))
    message.set_subject('Please confirm your email address')
    message.set_html(render_template("email/signup_confirmation.html", user=user))
    message.set_from('RKTIK Email Confirmation')

    try:
        status, msg = send_email(message)
    except SendGridClientError, e:
        logger.error("Client error sending confirmation email: {}".format(e))
        if current_app.config.get('DEBUG') is True:
            logger.warning("User is being auto validated in debug environment")
            user.validate()
    except SendGridServerError, e:
        logger.error("Server error sending confirmation email: {}".format(e))
        logger.warning("User is being auto validated in debug environment")
        user.validate()


def valid_redirect(path):
    """Return True if path is in rktik domain"""
    from flask import current_app
    return path if path and path.startswith(current_app.config.get('SERVER_HOST')) else None
