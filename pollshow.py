import datetime
import time
import sqlite3
import urllib.request
import configparser
import imgkit
import sys
import tweepy
import pprint
import logging as l

l.basicConfig(level = l.INFO,
              format='%(asctime)s  %(levelname)-10s %(processName)s  %(name)s %(message)s',
              handlers=(l.StreamHandler(stream=sys.stdout),
                        l.FileHandler(filename="messages.log")))

def print_tweet(imgkit, wkconfig, id):
    req = urllib.request.Request('https://twitter.com/i/cards/tfw/v1/{}?cardname=poll2choice_text_only'.format(id))
    req.add_header("Referer", "https://twitter.com/polls/status/{}".format(id))
    html_name = "{}.html".format(id)
    png_name = "{}.png".format(id)
    with urllib.request.urlopen(req) as response:
        the_page = response.read()
        with open(html_name, mode='wb') as file:
            file.write(the_page)

    options = {
        'width': '400',
        'height': '100'
    }
    imgkit.from_file(filename=html_name, output_path=png_name, config=wkconfig, options=options)
    return png_name


def twitter_login(config, key,secret):
    l.info('logging in twitter')
    auth = tweepy.OAuthHandler(key, secret)

    if config.has_option('User', 'user.access_token') and config.has_option('User', 'user.access_token_secret'):
        l.info('We got the access token')
    else:
        l.warning('no access token found, getting access token')
        try:
            redirect_url = auth.get_authorization_url()
            l.debug("redirect url: {}", redirect_url)
        except tweepy.TweepError:
            l.error('Error! Failed to get request token.')
            exit(1)
        verifier = input('Verifier:')
        try:
            auth.get_access_token(verifier)
        except tweepy.TweepError:
            l.error('Error! Failed to get access token.')
            exit(1)
        l.debug('saving access token')
        config.remove_section("User")
        config.add_section("User")
        config.set('User', 'user.access_token', auth.access_token)
        config.set('User', 'user.access_token_secret', auth.access_token_secret)

        secret_fp = open(secret_properties, mode='w')
        config.write(secret_fp)
    auth.set_access_token(config.get('User', 'user.access_token'), config.get('User', 'user.access_token_secret'))
    return tweepy.API(auth)


def ensure_tables(conn: sqlite3.Connection):
    c = conn.cursor()
    c.executescript("CREATE TABLE IF NOT EXISTS variables (key TEXT, value TEXT, PRIMARY KEY ('key'));"
                    "CREATE TABLE IF NOT EXISTS polls (tweet TEXT, render_path TEXT, render_date TEXT, PRIMARY KEY ('tweet'));"
                    "CREATE TABLE IF NOT EXISTS mentions (tweet TEXT, user TEXT, poll_tweet TEXT,"
                    "  reply_tweet TEXT, reply_date TEXT, PRIMARY KEY ('tweet','user','poll_tweet'));")
    conn.commit()


def get_rendered(db: sqlite3.Cursor, in_reply_to_status_id: str):
    db.execute("select render_path from polls where tweet = ?", [in_reply_to_status_id])
    result = db.fetchone()
    if result is None:
        return None
    else:
        return result[0]


def get_old_reply(db: sqlite3.Cursor, id_str, screen_name, in_reply_to_status_id):
    db.execute("SELECT reply_tweet FROM mentions WHERE tweet = ? AND user = ? AND poll_tweet = ?", (id_str, screen_name, in_reply_to_status_id))
    result = db.fetchone()
    if result is None:
        return None
    else:
        return result[0]


def mark_rendered(db: sqlite3.Cursor, in_reply_to_status_id: str, png: str):
    now = datetime.datetime.now().replace(microsecond=0).isoformat()
    db.execute("INSERT OR REPLACE INTO polls (tweet, render_path, render_date) values (?, ? ,?)", (in_reply_to_status_id, png, now))


def get_next_mentions(db: sqlite3.Cursor, api: tweepy.API):
    db.execute("SELECT value FROM variables WHERE key = 'last.mention'")
    latest = db.fetchone()
    if latest is None:
        l.info("no latest")
        return api.mentions_timeline()
    else:
        l.info("latest is: %s", latest[0])
        return api.mentions_timeline(since_id=latest[0])


# main
secret_properties = 'secret.properties'

config = configparser.RawConfigParser()
config.read(secret_properties)
if config.has_option("Main", "wkhtmltoimage"):
    wkpath = config.get("Main", "wkhtmltoimage")
    l.debug("wkpath={}", wkpath)
else:
    l.error("No wkhtmltoimage path on config")
    exit(1)
wkconfig = imgkit.config(wkhtmltoimage=wkpath)

api = twitter_login(config, config.get("app_key"), config.get("app_secret"))

conn = sqlite3.connect('pollshow.db')
ensure_tables(conn)
db = conn.cursor()

# database structure:
# variables { key, value } (e.g. "last.mention": "2312452524324332" )
# polls {tweet, render_path, render_date}
# mentions { tweet, user, poll_tweet, reply_tweet, reply_date }
#   that is: we found 'tweet' by 'user' in mentions, it required a render of 'poll_tweet', we replied with 'reply_tweet'
#   in 'reply_date'

sleep_seconds = config.getint("Main", "sleep_seconds")
sleep_between_tweets = config.getint("Main", "sleep_between_tweets")

pp = pprint.PrettyPrinter(indent=2)

while True:
    l.info("getting next mentions")
    mentions = get_next_mentions(db, api)
    l.info("got %d mentions", len(mentions))
    sorted_mentions = sorted(mentions, key=lambda m: m.id_str)
    for m in sorted_mentions:
        pp.pprint("id: {} (in reply to: {}): {}".format(m.id, m.in_reply_to_status_id, m.text))
        if m.in_reply_to_status_id is not None:
            l.info("Rendering tweet %s", m.id)
            rendered = get_rendered(db, m.in_reply_to_status_id)
            if rendered is None:
                png = print_tweet(imgkit, wkconfig, m.in_reply_to_status_id)
                mark_rendered(db, m.in_reply_to_status_id, png)
            else:
                png = rendered

            # if already replied
            oldReply = get_old_reply(db, m.id_str, m.author.screen_name, m.in_reply_to_status_id)
            if oldReply is None:
                l.info("Posting update in reply to %s with image %s", m.id, png)
                posted = api.update_with_media(
                    filename=png,
                    in_reply_to_status_id=m.id,
                    in_reply_to_status=m.id,
                    in_reply_to_status_id_str=m.id_str,
                    in_reply_to_screen_name=m.author.screen_name,
                    in_reply_to_user_id=m.author.id,
                    in_reply_to_user_id_str=m.author.id_str,
                    status="@{} Here is an image of the poll's results:".format(m.author.screen_name))
                pp.pprint(posted.__dict__)
                now = datetime.datetime.now().replace(microsecond=0).isoformat()
                parameters = (m.id_str, m.author.screen_name,
                              m.in_reply_to_status_id, posted.id_str, now)
                l.info("saving mention (tweet, user, poll_tweet, reply_tweet, reply_date) as {}".format(parameters))
                db.execute("INSERT INTO mentions (tweet, user, poll_tweet, reply_tweet, reply_date)"
                           " VALUES (?,?,?,?,?)", parameters)
                conn.commit()
                l.info("saved mention (tweet, user, poll_tweet, reply_tweet, reply_date) as %s", parameters)
                l.info("sleeping for %d before next tweet", sleep_between_tweets)
                time.sleep(sleep_between_tweets)
            else:
                l.info("already got a reply for {} by {}, skipping".format(m.id_str, m.author.screen_name))
        l.info("saving latest mention {} to db".format(m.id_str))
        db.execute("INSERT OR REPLACE INTO variables (key,value) VALUES (?,?)", ("last.mention", m.id_str))
        conn.commit()
    l.info("sleeping for %d seconds", sleep_seconds)
    time.sleep(sleep_seconds)
