# -*- coding: utf-8 -*-
"""
    default_config
    ~~~~~

    Base config object.

    :copyright: (c) 2013 by Vincent Ahrend.
"""
import datetime

DEBUG = False
USE_DEBUG_SERVER = False
HEROKU = False

CACHE_TYPE = 'simple'

# Don't let Flask Debug Toolbar interrupt redirects (BREAKS HTTPAUTH)
DEBUG_TB_INTERCEPT_REDIRECTS = False

SESSION_EXPIRATION_TIME = datetime.timedelta(minutes=15)

TIMEZONE = 'Europe/Berlin'

#
# Performance options
#

# Only count one upvote per user account, even if they voted with more than
# one Persona
UPVOTES_FILTER_DISTINCT_USERS = True
