#!/usr/bin/python3
import array
import base64
import datetime
import hashlib
import math
import os
import random
import re
import requests
import shutil
import subprocess
import zlib
import sqlite3
import signal
import time
import string
import getpass
import json

from dateutil import tz
from binascii import hexlify, unhexlify

from Crypto.Cipher import AES
from Crypto.Protocol.KDF import PBKDF2

from bs4 import BeautifulSoup
from sys import argv, exit, stdout

# Where should the cache file be stored?
# This file is used to store generated device id, session id, username and password
CACHE_PATH = os.path.dirname(os.path.realpath(__file__))+'/.crcache'
# Where should the subtitle file be stored?
SUBTITLE_TEMP_PATH = os.path.dirname(os.path.realpath(__file__))+'/.ass'

# How many days must pass before the show isn't considered followed
QUEUE_FOLLOWING_THRESHOLD = 14
# How many percentage of the video you must've seen for it to count as seen
QUEUE_WATCHED_THRESHOLD = 0.8

# Should it authenticate automatically on startup? (disables cookie import)
AUTHENTICATE = True
# Should the cookies be extracted from chrome automatically?
USE_CHROME_COOKIES = False
# Path to the chrome cookie sqlite database
CHROME_COOKIE_FILE_PATH = os.path.expanduser('~/.config/google-chrome/Default/Cookies')
# On Mac, CHROME_COOKIE_DECRYPT_PASS is your password from Keychain
# On Linux, CHROME_COOKIE_DECRYPT_PASS is 'peanuts' by default
#    If you use libsecret, you can find the password by running "secret-tool search application chrome"
CHROME_COOKIE_DECRYPT_PASS = 'peanuts'
# 1003 on Mac, 1 on Linux
CHROME_COOKIE_DECRYPT_ITERATIONS = 1
# Same thing but for Firefox
USE_FIREFOX_COOKIES = False
with open(os.path.expanduser('~/.mozilla/firefox/profiles.ini')) as f:
    FIREFOX_PROFILE_NAME, = re.findall('\[Profile0\]\n.+?Path=(.+?\.default)', f.read(), re.S)
FIREFOX_COOKIE_FILE_PATH = os.path.expanduser('~/.mozilla/firefox/{}/cookies.sqlite'.format(FIREFOX_PROFILE_NAME))
# You can also specify cookies manually here
cookies = {
    'sess_id': '',
    'c_userid': '',
    'c_userkey': ''
}

# END OF CONFIGURATION

api_headers = {
    'Host': 'api.crunchyroll.com',
    'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64; rv:51.0) Gecko/20100101 Firefox/51.0',
}

rpc_headers = {
    'Host': 'www.crunchyroll.com',
    'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64; rv:51.0) Gecko/20100101 Firefox/51.0',
}

authenticated = False
queueSoup = None

class color:
   PURPLE = '\033[95m'
   CYAN = '\033[96m'
   DARKCYAN = '\033[36m'
   BLUE = '\033[94m'
   GREEN = '\033[92m'
   YELLOW = '\033[93m'
   RED = '\033[91m'
   BOLD = '\033[1m'
   UNDERLINE = '\033[4m'
   END = '\033[0m'

colors = {}
for i in dir(color):
    if not i.startswith("__"): colors[i] = getattr(color, i)

print_overridable_len = 0
#If string is empty, it ends override by cleaning up the current line
def print_overridable(str = '', end = False):
    global print_overridable_len
    old_len = print_overridable_len
    cleanstr = str
    for i,v in colors.items():
        cleanstr = cleanstr.replace(v, '')
    print_overridable_len = len(cleanstr)
    if old_len > print_overridable_len:
        str += ' '*(old_len-print_overridable_len)
    if end:
        print_overridable_len = 0
        print(str)
    else:
        print(str, end="\r", flush=True)

#End override by placing text on a new line
def print_under(str = ''):
    global print_overridable_len
    if len(str):
        print('\n'+str)
    else:
        print('')
    print_overridable_len = 0


def input_yes(question):
    answer = input(question+' (Y/N)? ')
    return answer.lower() == 'y'

def mmss(seconds):
    stamp = str(datetime.timedelta(seconds=int(float(seconds))))
    if stamp.startswith("0:"):
        stamp = stamp[2:]
    return stamp

def timestamp_to_datetime(ts):
    return (datetime.datetime.strptime(ts[:-7],'%Y-%m-%dT%H:%M:%S') + datetime.timedelta(hours=int(ts[-5:-3]), minutes=int(ts[-2:])) * -int(ts[-6:-5]+'1')).replace(tzinfo=tz.tzutc())

def generate_key(mediaid, size=32):
    # Below: Do some black magic
    eq1 = int(int(math.floor(math.sqrt(6.9) * math.pow(2, 25))) ^ mediaid)
    eq2 = int(math.floor(math.sqrt(6.9) * math.pow(2, 25)))
    eq3 = (mediaid ^ eq2) ^ (mediaid ^ eq2) >> 3 ^ eq1 * 32
    # Below: Creates a 160-bit SHA1 hash
    shaHash = hashlib.sha1()
    stringHash = create_string([20, 97, 1, 2]) + str(eq3)
    shaHash.update(stringHash.encode(encoding='UTF-8'))
    finalHash = shaHash.digest()
    hashArray = array.array('B', finalHash)
    # Below: Pads the 160-bit hash to 256-bit using zeroes, incase a 256-bit key is requested
    padding = [0]*4*3
    hashArray.extend(padding)
    keyArray = [0]*size
    # Below: Create a string of the requested key size
    for i, item in enumerate(hashArray[:size]):
        keyArray[i] = item
    return hashArray.tostring()

def create_string(args):
    i = 0
    argArray = [args[2], args[3]]
    while(i < args[0]):
        argArray.append(argArray[-1] + argArray[-2])
        i = i + 1
    finalString = ""
    for arg in argArray[2:]:
        finalString += chr(arg % args[1] + 33)
    return finalString

def decode_subtitles(id, iv, data):
    compressed = True
    key = generate_key(id)
    iv = base64.b64decode(iv)
    data = base64.b64decode(data)
    cipher = AES.new(key, AES.MODE_CBC, iv)
    decryptedData = cipher.decrypt(data)

    if compressed:
        return zlib.decompress(decryptedData)
    else:
        return decryptedData

def convert(script):
    soup = BeautifulSoup(script, 'xml')
    header = soup.find('subtitle_script')
    header = "[Script Info]\nTitle: "+header['title']+"\nScriptType: v4.00+\nWrapStyle: "+header['wrap_style']\
             + "\nPlayResX: "+header['play_res_x']+"\nPlayResY: "+header['play_res_y']+"\n\n"
    styles = "[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, " \
             "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, " \
             "Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
    events = "\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    stylelist = soup.findAll('style')
    eventlist = soup.findAll('event')

    for style in stylelist:
        if style['scale_x'] or style['scale_y'] == '0':
            style['scale_x'], style['scale_y'] = '100', '100'  # Fix for Naruto 1-8 where it's set to 0 but ignored
        styles += "Style: " + style['name'] + "," + style['font_name'] + "," + style['font_size'] + ","\
                  + style['primary_colour'] + "," + style['secondary_colour'] + "," + style['outline_colour'] + ","\
                  + style['back_colour'] + "," + style['bold'] + "," + style['italic'] + ","\
                  + style['underline'] + "," + style['strikeout'] + "," + style['scale_x'] + ","\
                  + style['scale_y'] + "," + style['spacing'] + "," + style['angle'] + ","\
                  + style['border_style'] + "," + style['outline'] + "," + style['shadow'] + ","\
                  + style['alignment'] + "," + style['margin_l'] + "," + style['margin_r'] + ","\
                  + style['margin_v'] + "," + style['encoding'] + "\n"

    for event in eventlist:
        events += "Dialogue: 0,"+event['start']+","+event['end']+","+event['style']+","\
                  + event['name']+","+event['margin_l']+","+event['margin_r']+","+event['margin_v']\
                  + ","+event['effect']+","+event['text']+"\n"

    formattedsubs = header+styles+events
    return formattedsubs

def decrypt_chrome_cookie(encrypted_value):
    def clean(x):
        return x[:-x[-1]].decode('utf8')

    # Trim off the 'v11' that Chrome prepends
    encrypted_value = encrypted_value[3:]

    salt = b'saltysalt'
    iv = b' ' * 16
    my_pass = CHROME_COOKIE_DECRYPT_PASS.encode('utf8')

    key = PBKDF2(my_pass, salt, 16, CHROME_COOKIE_DECRYPT_ITERATIONS)
    cipher = AES.new(key, AES.MODE_CBC, IV=iv)

    decrypted = cipher.decrypt(encrypted_value)
    return clean(decrypted)

def get_chrome_cookies():
    conn = sqlite3.connect(CHROME_COOKIE_FILE_PATH)
    c = conn.cursor()
    c.execute('SELECT name, encrypted_value FROM cookies WHERE host_key == ".crunchyroll.com" and (name == "sess_id" OR name == "c_userid" OR name == "c_userkey");')
    rows = c.fetchall()
    c.close()
    conn.close()
    out = {}
    for row in rows:
        out[row[0]] = decrypt_chrome_cookie(row[1])
    return out

def get_firefox_cookies():
    conn = sqlite3.connect(FIREFOX_COOKIE_FILE_PATH)
    c = conn.cursor()
    c.execute('SELECT name, value FROM moz_cookies WHERE baseDomain == "crunchyroll.com" and (name == "sess_id" OR name == "c_userid" OR name == "c_userkey");')
    rows = c.fetchall()
    c.close()
    conn.close()
    out = dict(rows)
    return out

def update_cookies():
    global authenticated
    global cookies
    if USE_CHROME_COOKIES:
        cookies = get_chrome_cookies()
        print(color.GREEN+'Cookies were imported from Chrome'+color.END)
    elif USE_FIREFOX_COOKIES:
        cookies = get_firefox_cookies()
        print(color.GREEN+'Cookies were imported from Firefox'+color.END)

    if len(cookies['sess_id']) == 0:
        print(color.YELLOW+'Warning: sess_id is empty, running as guest'+color.END)
    else:
        # It should be possible to generate a new sess_id using c_userid and c_userkey, somehow
        if len(cookies['c_userid']) == 0 or len(cookies['c_userkey']) == 0:
            print(color.YELLOW+'Warning: c_userid or c_userkey is empty'+color.END)

        success = True # TODO: Perform some fetch to verify that the cookie is valid here!
        if not success and authenticated:
            print(color.YELLOW+'Warning: Your sess_id is invalid, you are now running as a guest'+color.END)
        elif success and not authenticated:
            print(color.GREEN+'You are now authenticated'+color.END)
        authenticated = success

ram_cache = None
def get_cache(key = None):
    def _get_cache():
        global ram_cache
        if ram_cache:
            return ram_cache
        if os.path.isfile(CACHE_PATH):
            with open(CACHE_PATH, 'r') as file:
                cache = file.read()
                if cache != "":
                    cache = json.loads(cache)
                    return cache
        return {}
    cache = _get_cache()
    if key != None:
        if key in cache:
            return cache[key]
        return None
    return cache

def set_cache(arg1, value = None):
    global ram_cache
    if value != None:
        cache = get_cache()
        cache[arg1] = value
    else:
        cache = arg1
    with open(CACHE_PATH, 'w+') as file:
        ram_cache = cache
        json.dump(cache, file)

def unset_cache(*keys):
    cache = get_cache()
    for key in keys:
        del cache[key]
    set_cache(cache)

def get_device_id():
    device_id = get_cache("device_id")
    if device_id != None: return device_id
    # Create a random device id and cache it
    print("Creating device id and caching it")
    char_set = string.ascii_letters + string.digits
    device_id = "".join(random.sample(char_set, 32))
    set_cache("device_id", device_id);
    return device_id

def create_session():
    data = {
        "device_id": get_device_id(),
        "device_type": "com.crunchyroll.iphone",
        "access_token": "QWjz212GspMHH9h"
    }
    expires = get_cache("expires")
    auth = get_cache("auth")
    if expires and expires < time.time():
        unset_cache("expires", "auth")
        print_overridable(color.RED+'Authentication has expired, must reauthenticate'+color.END, True)
    elif auth:
        data["auth"] = auth

    print_overridable('Creating session...')
    soup = BeautifulSoup(requests.get('http://api.crunchyroll.com/start_session.0.xml', headers=api_headers, params=data, cookies=cookies).text, 'xml')
    if soup.response.error.text == 'true':
        print_overridable(color.RED+'Error: '+soup.response.message.text+color.END, True)
        return None
    else:
        print_overridable(color.GREEN+'Session created'+color.END, True)
        sess_id = soup.response.data.session_id.text
        if not soup.response.data.auth.is_empty_element:
            #Auth is renewd everytime a new session is started
            set_cache("auth", soup.response.data.auth.text);
            set_cache("expires", timestamp_to_datetime(soup.response.data.expires.text).timestamp());
            finish_auth(sess_id)
            return None #We return None to short-circuit the caller since the session is already authenticated
        return sess_id

def finish_auth(sess_id):
    global authenticated
    global cookies
    cookies['sess_id'] = sess_id
    set_cache("session_id", sess_id);
    print_overridable(color.GREEN+'You are now authenticated'+color.END, True)
    authenticated = True

def authenticate_session(user, password, sess_id):
    global authenticated
    data = {
        "account": user,
        "password": password,
        "session_id": sess_id
    }
    print_overridable('Authenticating...')
    soup = BeautifulSoup(requests.get('https://api.crunchyroll.com/login.0.xml', headers=api_headers, params=data).text, 'xml')
    if soup.response.error.text == 'true':
        print_overridable(color.RED+'Error: '+soup.response.message.text+color.END, True)
        authenticated = False
    else:
        set_cache("auth", soup.response.data.auth.text);
        set_cache("expires", timestamp_to_datetime(soup.response.data.expires.text).timestamp());
        finish_auth(sess_id)

#TODO: Currently the session is dropped entirely if the authentication fails. We want to cache and re-use it on the next attempt!
def authenticate(args):
    global unassigned_session
    session_id = get_cache("session_id");
    if session_id and "new" not in args:
        #TODO: Add a check here to make sure that the session hasn't expired
        finish_auth(session_id)
        return
    session_id = create_session()
    if session_id:
        user = get_cache("user")
        if not user:
            user = input('Username: ')
            if input_yes("Remember username"):
                set_cache("user", user);
                print(color.GREEN+'Username saved'+color.END)
        password = get_cache("password")
        if not password:
            password = getpass.getpass()
            if input_yes("Remember password"):
                set_cache("password", password);
                print(color.GREEN+'Password saved'+color.END)
        authenticate_session(user, password, session_id)

def update_queue():
    global authenticated
    global queueSoup
    if not authenticated:
        if queueSoup:
            print(color.YELLOW+'Error: Could not update queue. You are not authenticated'+color.END)
        else:
            print(color.RED+'Warning: Could not load queue. You are not authenticated'+color.END)
        return

    if queueSoup:
        print_overridable('Updating queue...')
        resultStr = 'Queue updated'
    else:
        print_overridable('Loading queue...')
        resultStr = 'Queue loaded'
    data = {
        'session_id': cookies['sess_id'],
        'fields': 'last_watched_media,last_watched_media_playhead,most_likely_media,most_likely_media_playhead,media.media_id,media.series_id,media.name,media.episode_number,media.available_time,media.duration,media.collection_name,media.url,series,series.name'
    }
    queueSoup = BeautifulSoup(requests.get('http://api.crunchyroll.com/queue.0.xml', headers=api_headers, params=data, cookies=cookies).text, 'xml')
    queueSoup.encoding = 'utf-8'
    if queueSoup.response.error.text == "true":
        if queueSoup.response.code.text == "bad_session":
            msg = "Your session has expired. You are no longer authenticated"
            unset_cache("session_id")
            authenticated = False
        else:
            msg = "{} ({})".format(queueSoup.response.message.text, queueSoup.response.code.text)
        print_overridable(color.RED+'Error: Could not fetch queue. '+msg+color.END, True)
    else:
        print_overridable(color.GREEN+resultStr+color.END, True)

def run_media(pageurl):
    global queueSoup
    #seriesid = None
    while True:
        mediaid = re.search(r'[^\d](\d{6})(?:[^\d]|$)', pageurl).group(1)

        data = {
            'req': 'RpcApiVideoPlayer_GetStandardConfig',
            'media_id': mediaid,
            'video_format': '108',
            'video_quality': '80',
            'current_page': pageurl
        }

        print_overridable('Fetching media information...')
        config = requests.get('http://www.crunchyroll.com/xml/', headers=rpc_headers, params=data, cookies=cookies)
        config.encoding = 'utf-8'
        print_overridable()
        if config.status_code != 200:
            print(color.RED+'Error: '+config.text+color.END)
            return

        #What is this even? Does it catch some specific media or 404 pages?
        if len(config.text) < 100:
            print(config.url)
            print(config.text)
            return

        config = BeautifulSoup(config.text, 'lxml-xml')

        #Check for errors
        error = config.find('error')
        if error:
            print(color.RED+'Error: '+error.msg.text+color.END)
            return

        #Check if media is unavailable
        error = config.find('upsell')
        if error:
            print(color.RED+'Error: Media is only available for premium members'+color.END)
            return

        nextEpisode = config.find('nextUrl').text
        series = config.series_title.text
        epnum = config.episode_number.text
        episode = config.episode_title.text
        duration = config.duration.text
        print('{} - E{}'.format(series, epnum))
        print(episode)
        print('Duration: {}'.format(mmss(duration)))

        sub = config.find('subtitle', attrs={'link': None})
        if sub:
            print_overridable('Preparing subtitles...')
            _id = int(sub['id'])
            _iv = sub.iv.text
            _subdata = sub.data.text
            # print(_id, _iv, _subdata)
            open(SUBTITLE_TEMP_PATH, 'w').write(convert(decode_subtitles(_id, _iv, _subdata).decode('utf-8')))

        print_overridable('Fetching stream information...')
        data['req'] = 'RpcApiVideoEncode_GetStreamInfo'
        streamconfig = BeautifulSoup(requests.post('http://www.crunchyroll.com/xml', headers=rpc_headers, data=data, cookies=cookies).text, 'lxml-xml')
        streamconfig.encoding = 'utf-8'

        print_overridable('Starting stream...')
        playhead = 0
        if not streamconfig.host.text:
            url = streamconfig.file.text
            subprocess.call(['mpv', url])
        else:
            host = streamconfig.host.text
            file = streamconfig.file.text
            if re.search('fplive\.net', host):
                url1, = re.findall('.+/c[0-9]+', host)
                url2, = re.findall('c[0-9]+\?.+', host)
            else:
                url1, = re.findall('.+/ondemand/', host)
                url2, = re.findall('ondemand/.+', host)

            subarg = ""
            if sub: subarg = " --sub-file "+SUBTITLE_TEMP_PATH
            proc = subprocess.Popen(
                ["rtmpdump -a '"+url2+"' --flashVer 'WIN 11,8,800,50' -m 15 --pageUrl '"+pageurl+"' --rtmp '"+url1+"' --swfVfy http://www.crunchyroll.com/vendor/ChromelessPlayerApp-c0d121b.swf -y '"+file+"' | mpv --force-seekable=yes"+subarg+" -"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                bufsize=1,
                shell=True
            )

            # Pick up stderr for playhead information
            while True:
                line = proc.stderr.readline().decode("utf-8")
                if line == '' and proc.poll() is not None:
                    break
                timestamp = re.search('AV: ([0-9]{2}:[0-9]{2}:[0-9]{2}) / ([0-9]{2}:[0-9]{2}:[0-9]{2})', line)
                if timestamp:
                    current = [int(i) for i in timestamp.group(1).split(":")]
                    playhead = (current[0]*60+current[1])*60+current[2]
                    print_overridable('Playhead: {}'.format(mmss(playhead)))

        print_under()
        if sub: os.remove(SUBTITLE_TEMP_PATH)

        if authenticated and input_yes('Do you want to update seen duration to {}/{}'.format(mmss(playhead), mmss(duration))):
            print_overridable('Updating seen duration...')
            data = {
                'req': 'RpcApiVideo_VideoView',
                'media_id': mediaid,
                'cbcallcount': 0,
                'cbelapsed': 30,
                'playhead': config.duration
            }
            resp = requests.get('http://www.crunchyroll.com/xml/', headers=rpc_headers, params=data, cookies=cookies)
            if resp.status_code != 200:
                print_overridable(color.RED+'Error: '+resp.text+color.END, True)
            else:
                print_overridable(color.GREEN+'Seen duration was saved'+color.END, True)
                update_queue() #We update the queue after marking episode as seen!

        if nextEpisode != "":
            if input_yes('Another episode is available, do you want to watch it'):
                pageurl = nextEpisode
            else:
                break
        else:
            print(color.RED+'No more episodes available'+color.END)
            break

def show_queue(args = []):
    crntDay = -1
    def following_title(air):
        nonlocal args
        nonlocal crntDay
        if "following" in args:
            localAir = air.astimezone(tz.tzlocal())
            weekDay = localAir.weekday()
            if weekDay > crntDay:
                crntDay = weekDay
                print('\n'+color.BOLD+localAir.strftime("%A")+color.END)

    if queueSoup is None or "update" in args:
        update_queue()

    if queueSoup is None:
        return

    items = [item for item in queueSoup.find_all('item')]
    if "following" in args:
        items.sort(key=lambda e: e.most_likely_media.available_time.string)
        items.sort(key=lambda e: timestamp_to_datetime(e.most_likely_media.available_time.text).astimezone(tz.tzlocal()).weekday())

    title = "All"
    if "following" in args:
        title = "Following"
    elif "watching" in args:
        title = "Watching"
    if "all" not in args:
        title += " (Unseen)"
    print(color.BOLD+title+':'+color.END)
    now = datetime.datetime.utcnow().replace(tzinfo=tz.tzutc())
    count = 0
    for item in items:
        media = item.most_likely_media
        last_media = item.last_watched_media
        last_playhead = item.last_watched_media_playhead.text
        if last_playhead == '':
            last_playhead = '0'
        if ("watching" not in args and "following" not in args) or not int(last_playhead) < 1:
            air = timestamp_to_datetime(media.available_time.text)
            seconds = math.ceil((now - air).total_seconds())
            if media.duration.text == "":
                following_title(air)
                print((color.YELLOW+'{} - E{} - {}'+color.END).format(media.collection_name.text, media.episode_number.text, mmss(-seconds)))
                count += 1
            else:
                seen = int(item.most_likely_media_playhead.text) >= int(media.duration.text) * QUEUE_WATCHED_THRESHOLD
                if "all" in args or not seen:
                    days = seconds/60/60/24
                    if "following" not in args or days < QUEUE_FOLLOWING_THRESHOLD:
                        following_title(air)
                        if seen:
                            print(color.GREEN, end='')
                        print('{} - E{} - {}'.format(media.collection_name.text, media.episode_number.text, media.find('name').text))
                        print(color.END, end='')
                        count += 1
    print('')
    if count == 0:
        print(color.RED+'No series found'+color.END)
    else:
        print((color.GREEN+'{} series found'+color.END).format(count))


def run_random(args):
    if queueSoup is None or "update" in args:
        update_queue()
    if queueSoup is None:
        return
    items = [item for item in queueSoup.find_all('item')]
    filtered = []
    for item in items:
        media = item.most_likely_media
        last_playhead = item.last_watched_media_playhead.text
        if last_playhead == '':
            last_playhead = '0'
        if not int(last_playhead) < 1:
            if int(item.most_likely_media_playhead.text) < int(media.duration.text) * QUEUE_WATCHED_THRESHOLD:
                filtered.append(media)
    run_media(random.choice(filtered).url.text)


def run_search(search):
    if search != "":
        if queueSoup is None:
            update_queue()

        if queueSoup is None:
            return

        print_overridable('Searching for \"{}\"...'.format(search))
        search = search.lower()
        media = None
        for item in queueSoup.findAll('item'):
            series_name = item.series.find('name').text
            if search in series_name.lower():
                media = item.most_likely_media
                break
        if media:
            print_overridable("")
            if input_yes('Found \"{} - E{} - {}\"\nDo you want to watch it'.format(media.collection_name.text, media.episode_number.text, media.find('name').text)):
                run_media(media.url.text)
        else:
            print_overridable(color.RED+'Could not find any series'+color.END, True)
    else:
       print(color.RED+'Error: Empty search query'+color.END)

def show_help(args = []):
    print(
        color.BOLD+'Crunchyroll CLI Help'+color.END+'\n\n'+
        color.BOLD+'URL'+color.END+'\n'+
                   '       You can watch a specific episode by providing its crunchyroll.com URL.\n\n'+
        color.BOLD+'COMMANDS'+color.END+'\n'+
        color.BOLD+'       queue'+color.END+' [all] [following|watching] [update]\n'+ = Series that you've started watching
                   '         Series where you\'ve seen past the watched threshold on the current episode are hidden unless "all" is provided.\n'+
                   '         "watching" will filter out all series where you haven\'t began watching any episodes yet.\n'+
                   '         "following" will filter out all series where an episode has been out for 2 weeks without you watching it.\n'+
                   '         "update" will fetch the queue.\n'+
        color.BOLD+'       watch'+color.END+' <search query>\n'+
        color.BOLD+'       rand'+color.END+' [update]\n'+
        color.BOLD+'       exit'+color.END+'\n'
    )

def main_loop(args = []):
    while True:
        if len(args) > 0:
            command = args[0].lower()
            if command == 'watch' or command == 'w':
                run_search(' '.join(args[1:]))
            elif command == 'queue' or command == 'q':
                show_queue(args[1:])
            elif command == 'auth' or command == 'a':
                authenticate(args[1:])
            elif command == 'rand' or command == 'r':
                run_random(args[1:])
            elif command == 'exit':
                exit()
            elif command == 'help':
                show_help(args[1:])
            elif re.search('^http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\(\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+$', args[0]):
                if re.search(r'[^\d](\d{6})(?:[^\d]|$)', args[0]):
                    run_media(args[0])
                else:
                    print(color.RED+'Error: Unknown url format'+color.END)
            else:
                print(color.RED+'Error: Unknown command '+command+color.END)
        args = input('> ').split()


def exit_signal_handler(signal = None, frame = None):
    print('')
    exit()
signal.signal(signal.SIGINT, exit_signal_handler) #Remove traceback when exiting with ctrl+c
signal.signal(signal.SIGTSTP, exit_signal_handler) #Remove stdout stuff when exiting with ctrl+z

print(color.BOLD+'Welcome to '+color.YELLOW+'Crunchyroll CLI'+color.END)
if len(argv) < 2 or argv[1].lower() != 'help': #Do not print this message if they're already calling help
    print('Don\'t know what to do? Type "'+color.BOLD+'help'+color.END+'"')
print()
if not AUTHENTICATE: #Do not prepare cookies if using auth
    update_cookies()
if not (len(argv) > 1 and argv[1].lower() == 'auth') and AUTHENTICATE: #Do not authenticate here if the auth command is being called anyway
    authenticate([])
try: #Remove traceback when exiting with ctrl+d
    main_loop(argv[1:])
except EOFError:
    exit_signal_handler()
