#!/usr/bin/env python


import os
import sys
import logging
import argparse
import json
import yaml
import praw
import random

from re import sub
from datetime import datetime, timedelta
from praw.errors import (InvalidUser, InvalidUserPass, RateLimitExceeded,
                        HTTPException, OAuthAppRequired)
from praw.objects import Comment, Submission

path = os.path.dirname(os.path.realpath(__file__))
os.chdir(path);

logging.basicConfig(stream=sys.stdout)
log = logging.getLogger(__name__)
log.setLevel(level=logging.DEBUG)

parser = argparse.ArgumentParser()
parser.add_argument(
    '-c',
    '--config',
    help="config file to use instead of the default shreddit.cfg"
)
parser.add_argument(
    '-u',
    '--user',
    help="user to override user in config file"
)
parser.add_argument(
    '-p',
    '--password',
    help="password to override password in config file"
)
parser.add_argument(
    '-r',
    '--refresh_token',
    help="run with a token instead of password"
)
parser.add_argument(
    '-j',
    '--json',
    help="run with a json string input instead of shreddit.yml"
)
args = parser.parse_args()
if args.json:
  config = json.loads(args.json)
else:
    if args.config:
        config_file = args.config
    else:
        config_file = path+'/shreddit.yml'

    with open(config_file, 'r') as fh:
        config = yaml.safe_load(fh)
    if config is None:
        raise Exception("No config options passed!")


if args.user:
    config['username'] = args.user

if args.password:
    config['password'] = args.password

if args.refresh_token:
    config['refresh_token'] = args.refresh_token
elif 'refresh_token' not in config:
    config['refresh_token'] = None

save_directory = config.get('save_directory', '.')

r = praw.Reddit(user_agent="shreddit/4.3")
if save_directory:
    r.config.store_json_result = True

for k, v in config.iteritems():     
    if type(v) is unicode:
        if v == 'True':
            config[k] = True
        if v == 'False':
            config[k] = False
        if v.isdigit():
            config[k] = int(v)
        if v == '[]':
            config[k] = []


if config.get('verbose', True):
    log_level = config.get('debug', 'DEBUG')
    log.setLevel(level=getattr(logging, log_level))

if not ('username' in config and 'password' in config) and config['refresh_token'] == None:
    log.error("No login information provided. Exiting...");
    exit();

try:
    # Try to login with OAuth2
    log.debug("trying to login with oauth2");
    r.refresh_access_information(config['refresh_token'])
    log.debug("Logged in with OAuth.")
except (HTTPException, OAuthAppRequired) as e:
    log.warning('''You should migrate to OAuth2 using get_secret.py before
            Reddit disables this login method.''')
    try:
        try:
            r.login(config['username'], config['password'])
        except InvalidUserPass as e:
#            r.login()  # Supply details on the command line
            log.info("Couldn't log in");
            raise e
    except InvalidUser as e:
        raise InvalidUser("User does not exist.", e)
    except InvalidUserPass as e:
        raise InvalidUserPass("Specified an incorrect password.", e)
    except RateLimitExceeded as e:
        raise RateLimitExceeded("You're doing that too much.", e)

log.info("Logged in as {user}.".format(user=r.user))
log.debug("Deleting messages before {time}.".format(
    time=datetime.now() - timedelta(hours=config['hours'])))

whitelist = config.get('whitelist', [])
whitelist_ids = config.get('whitelist_ids', [])

if whitelist:
    whitelist = set([subr.lower() for subr in whitelist])
    log.debug("Keeping messages from subreddits {subs}".format(
        subs=', '.join(whitelist))
    )


def get_sentence():
    return '''I have been Shreddited for privacy!'''


def get_things(after=None):
    limit = None
    item = config.get('item', 'comments')
    sort = config.get('sort', 'new')
    log.debug("Deleting items: {item}".format(item=item))
    if item == "comments":
        return r.user.get_comments(limit=limit, sort=sort)
    elif item == "submitted":
        return r.user.get_submitted(limit=limit, sort=sort)
    elif item == "overview":
        return r.user.get_overview(limit=limit, sort=sort)
    else:
        raise Exception("Your deletion section is wrong")


def remove_things(things):
    for thing in things:
        log.debug('Looking at: {thing}'.format(thing=thing))
        # Seems to be in users's timezone. Unclear.
        thing_time = datetime.fromtimestamp(thing.created_utc)
        # Exclude items from being deleted unless past X hours.
        after_time = datetime.now() - timedelta(hours=config.get('hours', 24))
        if thing_time > after_time:
            continue
        # For edit_only we're assuming that the hours aren't altered.
        # This saves time when deleting (you don't edit already edited posts).
        if config.get('edit_only'):
            end_time = after_time - timedelta(hours=config.get('hours', 24))
            if thing_time < end_time:
                    continue

        if str(thing.subreddit).lower() in whitelist \
           or thing.id in config.get('whitelist_ids', []):
            continue

        if config.get('whitelist_distinguished') and thing.distinguished:
            continue
        if config.get('whitelist_gilded') and thing.gilded:
            continue
        if 'max_score' in config and thing.score > config['max_score']:
            continue

        if config.get('save_directory'):
            save_directory = config['save_directory']
            if not os.path.exists(save_directory):
                os.makedirs(save_directory)
            with open("%s/%s.json" % (save_directory, thing.id), "w") as fh:
                json.dump(thing.json_dict, fh)

        if config.get('trial_run'):  # Don't do anything, trial mode!
            log.debug("Would have deleted {thing}: '{content}'".format(
                thing=thing.id, content=thing))
            continue

        if config.get('clear_vote'):
            thing.clear_vote()

        if isinstance(thing, Submission):
            log.info('Deleting submission: #{id} {url}'.format(
                id=thing.id,
                url=thing.url.encode('utf-8'))
            )
        elif isinstance(thing, Comment):
            replacement_text = get_sentence()
            log.debug('here');

            msg = '/r/{3}/ #{0} with:\n\t"{1}" to\n\t"{2}"'.format(
                thing.id,
                sub(b'\n\r\t', ' ', thing.body[:78].encode('utf-8')),
                replacement_text[:78],
                thing.subreddit
            )

            if config.get('edit_only'):
                log.info('Editing (not removing) {msg}'.format(msg=msg))
            else:
                log.info('Editing and deleting {msg}'.format(msg=msg))
                thing.edit(replacement_text)
        if not config.get('edit_only'):
            thing.delete()

remove_things(get_things())
log.info("Done shredditing. Run again to shred more items.")
