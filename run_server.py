#!/usr/bin/python
# -*- coding: utf-8 -*-
"""
    run_server
    ~~~~~

    Setup and run a Glia server. See glia/ directory.

    :copyright: (c) 2013 by Vincent Ahrend.
"""

from gevent import monkey
monkey.patch_all()

from glia import create_app, socketio
from worker import periodic_schedule
from socketio.server import SocketIOServer

app = create_app()


if __name__ == '__main__':
    periodic_schedule()

    if app.config['USE_DEBUG_SERVER']:
        # flask development server
        socketio.run(app, host=app.config['SERVER_HOST'], port=app.config['SERVER_PORT'], use_reloader=True)
    else:
        glia_server = SocketIOServer(('0.0.0.0', app.config['SERVER_PORT']), app)
        glia_server.serve_forever()
