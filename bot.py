import os

import redis
import telebot
from telebot.apihelper import FILE_URL
import ujson
from telebot.types import InlineKeyboardButton, InlineKeyboardMarkup
from collections import namedtuple

UserIDs = namedtuple('UserIDs', ['id', 'counts'])

token = os.environ['TELEGRAM_TOKEN']
CLARIFAI_TOKEN = os.environ['CLARIFAI_TOKEN']
r = redis.from_url(os.environ.get("REDIS_URL"))
bot = telebot.TeleBot(token)
from clarifai.rest import ClarifaiApp
from clarifai.rest import Image as ClImage

app = ClarifaiApp(api_key=CLARIFAI_TOKEN)
demogr_model = app.models.get('demographics')


@bot.callback_query_handler(func=lambda call: call and call.message and call.data and call.data.startswith('react-'))
def reaction(call):
    call.data = int(call.data.split('react-')[-1])
    key = str(call.message.chat.id) + '_' + str(call.message.message_id)
    reactions = r.get(key)
    if reactions:
        reactions_json = ujson.loads(reactions)
        for reaction in range(len(reactions_json)):
            if call.from_user.id in reactions_json[reaction]['users']:
                if reaction == call.data:
                    bot.answer_callback_query(call.id, text='Already ' + reactions_json[reaction]['label'] + ' this!')
                    return
                else:
                    reactions_json[reaction]['users'].remove(call.from_user.id)
            elif reaction == call.data:
                reactions_json[reaction]['users'].append(call.from_user.id)
    else:
        reactions_json = [{'label': '❤️', 'users': []}, {'label': '💔', 'users': []}]
        reactions_json[call.data]['users'].append(call.from_user.id)
    r.set(key, ujson.dumps(reactions_json))
    markup = InlineKeyboardMarkup()
    buttons = []
    for reaction in range(len(reactions_json)):
        if len(reactions_json[reaction]['users']):
            button_text = reactions_json[reaction]['label'] + ' ' + str(len(reactions_json[reaction]['users']))
        else:
            button_text = reactions_json[reaction]['label']
        buttons.append(InlineKeyboardButton(button_text, callback_data='react-{}'.format(reaction)))
    markup.add(*buttons)
    try:
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=markup)
    except:
        pass
    bot.answer_callback_query(call.id, 'You ' + reactions_json[call.data]['label'] + ' this')


@bot.message_handler(content_types=['photo'])
def handle_photo(msg):
    markup = InlineKeyboardMarkup()
    markup.add(
        InlineKeyboardButton('❤️', callback_data='react-0'),
        InlineKeyboardButton('💔', callback_data='react-1')
    )
    caption = msg.caption or ''
    # name = '<a href="tg://user?id={}">{}</a>\n'.format(msg.from_user.id, msg.from_user.first_name)
    name = '<b>{}</b>\n'.format(msg.from_user.first_name)
    if msg.reply_to_message:
        reply_message_id = msg.reply_to_message.message_id
    else:
        reply_message_id = None
    if len(name) + len(caption) <= 200:
        bot.send_photo(msg.chat.id, msg.photo[-1].file_id, reply_markup=markup, caption=name + caption,
                       parse_mode='HTML', reply_to_message_id=reply_message_id)
    else:
        bot.send_message(msg.chat.id, name + caption, parse_mode='HTML', reply_to_message_id=reply_message_id)
        bot.send_photo(msg.chat.id, msg.photo[-1].file_id, reply_markup=markup, reply_to_message_id=reply_message_id)

    try:
        bot.delete_message(msg.chat.id, msg.message_id)
    except Exception as e:
        print(e)


@bot.message_handler(commands=['ping'])
def pong(msg):
    bot.send_message(msg.chat.id, 'Pong!', reply_to_message_id=msg.message_id)


def tox_ratio(a, b):
    try:
        return round(((b - a) / (b + a)) * 100)
    except ZeroDivisionError:
        return 0


def get_ratio_emoji(ratio):
    if ratio == 0:
        return '😐'
    elif ratio > 0:
        return '😖'
    else:
        return '😍'


@bot.message_handler(commands=['stat', 'stats'])
def stats(msg):
    bot.send_chat_action(msg.chat.id, 'typing')
    if msg.chat.type != 'supergroup' and not msg.chat.username:
        bot.send_message(msg.chat.id, 'Stats available only for public supergroups with usernames!')
        return

    chat_id = str(msg.chat.id)
    keys = r.keys(chat_id + '_*')
    decoded_keys = []
    decoded_values = []

    data = []
    for key in keys:
        decoded_keys.append(key.decode('utf-8'))
    values = r.mget(decoded_keys)
    for value in values:
        decoded_values.append(ujson.loads(value))

    for key in range(len(decoded_keys)):
        data.append({decoded_keys[key].replace(chat_id + '_', ''): decoded_values[key]})
    if msg.reply_to_message:
        # User stats
        user_info = {'id': msg.reply_to_message.from_user.id, 'count_label_1': 0, 'count_label_2': 0}
        try:
            result = bot.get_chat_member(chat_id=chat_id, user_id=user_info['id'])
            name = result.user.first_name
            # user_name = '<a href="tg://user?id={}">{}</a>'.format(user_info['id'], name)
            user_name = name
        except:
            user_name = 'User {}'.format(user_info['id'])
        text = '<b>Stats for</b> {}\n'.format(user_name)
        for i in data:
            message_id = next(iter(i))
            label_1 = i[message_id][0]
            label_2 = i[message_id][1]
            if user_info['id'] in label_1['users']:
                user_info['count_label_1'] += 1
            if user_info['id'] in label_2['users']:
                user_info['count_label_2'] += 1
        ratio = tox_ratio(user_info['count_label_1'], user_info['count_label_2'])
        text += '({} - {}, {} - {}, {} - {}%)'.format('❤️', user_info['count_label_1'], '💔',
                                                      user_info['count_label_2'], get_ratio_emoji(ratio),
                                                      abs(ratio))
        bot.send_message(msg.chat.id, text, parse_mode='HTML', disable_web_page_preview=True)
    else:
        # 1. Top Users
        users = {}
        for i in data:
            message_id = next(iter(i))
            label_1 = i[message_id][0]
            label_2 = i[message_id][1]
            for user in label_1['users']:
                if users.get(user):
                    users[user]['count_label_1'] += 1
                else:
                    users[user] = {'count_label_1': 1, 'count_label_2': 0}
            for user in label_2['users']:
                if users.get(user):
                    users[user]['count_label_2'] += 1
                else:
                    users[user] = {'count_label_1': 0, 'count_label_2': 1}
        res = []
        for key, value in users.items():
            res.append(UserIDs(key, value.values()))

        sorted_users = sorted(res, key=lambda x: sum(x.counts), reverse=True)

        sorted_users = sorted_users[:10]
        text = '<b>🔝 Top users:</b>'
        text += '\n'

        for usr in range(len(sorted_users)):
            try:
                result = bot.get_chat_member(chat_id=chat_id, user_id=sorted_users[usr].id)
                name = result.user.first_name
                # user_name = '<a href="tg://user?id={}">{}</a>'.format(sorted_users[usr].id, name)
                user_name = name
            except:
                user_name = 'User {}'.format(sorted_users[usr].id)
            labels_list = list(sorted_users[usr].counts)
            ratio = tox_ratio(labels_list[0], labels_list[1])

            text += '<b>{}.</b> {} ({} - {}, {} - {}, {} - {}%)\n'.format(usr + 1, user_name, '❤️', labels_list[0],
                                                                          '💔',
                                                                          labels_list[1], get_ratio_emoji(ratio),
                                                                          abs(ratio))

        text += '\n'

        text += '<b>🔥 Hot posts</b>:'
        text += '\n'

        # Top posts
        sorted_labels_keys = sorted(data,
                                    key=lambda x: sum(
                                        [len(x[next(iter(x))][0]['users']), len(x[next(iter(x))][1]['users'])]),
                                    reverse=True)
        sorted_labels_keys = sorted_labels_keys[:10]

        for key in range(len(sorted_labels_keys)):
            message_id = next(iter(sorted_labels_keys[key]))
            element = sorted_labels_keys[key][message_id]
            label_1_count = len(element[0]['users'])
            label_2_count = len(element[1]['users'])
            text += '<b>{}.</b> <a href="https://t.me/{}/{}">Post {}</a> ({} - {}, {} - {})\n'.format(key + 1,
                                                                                                      msg.chat.username,
                                                                                                      message_id,
                                                                                                      message_id, '❤️',
                                                                                                      label_1_count,
                                                                                                      '💔',
                                                                                                      label_2_count)
        bot.send_message(msg.chat.id, text, parse_mode='HTML', disable_web_page_preview=True)


def parse_demogr_data(json_dict):
    faces = []
    for face in json_dict['outputs'][0]['data']['regions']:
        genders = []
        ages = []
        cultures = []
        ages.append(int(face['data']['face']['age_appearance']['concepts'][0]['name']))
        for gender in face['data']['face']['gender_appearance']['concepts']:
            genders.append({'name': gender['name'], 'value': gender['value']})
        for culture in face['data']['face']['multicultural_appearance']['concepts']:
            cultures.append({'name': culture['name'], 'value': culture['value']})
        faces.append({'genders': genders, 'ages': ages, 'cultures': cultures})
    return faces


def get_gender_str(s):
    return 'Male' if s == 'masculine' else 'Female'


def get_gender_text(genders):
    if len(genders) > 1:
        if genders[0]['value'] >= 0.3 and genders[1]['value'] >= 0.3 \
                or genders[1]['value'] >= 0.3 and genders[0]['value']:
            return '{} ({:.0%}) | {} ({:.0%})'.format(get_gender_str(genders[0]['name']), genders[0]['value'],
                                                      get_gender_str(genders[1]['name']), genders[1]['value'])
        else:
            if genders[0]['value'] > genders[1]['value']:
                idx = 0
            else:
                idx = 1
            return get_gender_str(genders[idx]['name'])
    else:
        return get_gender_str(genders[0]['name'])


def get_nationality_text(cultures):
    text = ''
    important_cultures = []
    for culture in cultures:
        if culture['value'] >= 0.3:
            important_cultures.append(culture)

    for culture in important_cultures:
        if text:
            text += ' | '
        if len(important_cultures) > 1:
            text += '{} ({:.0%})'.format(culture['name'], culture['value'])
        else:
            text += culture['name']
    return text


def create_demogr_data_str(faces):
    text = ''
    for face in faces:
        text += '<b>Gender:</b> ' + get_gender_text(face['genders'])
        text += '\n'
        text += '<b>Age:</b> ' + str(face['ages'][0])
        if face['ages'][0] < 18:
            text += ' ‼️🔞'
        text += '\n'
        text += '<b>Culture:</b> ' + get_nationality_text(face['cultures'])
        text += '\n\n'
    return text


@bot.message_handler(commands=['demographics', 'age', 'gender', 'culture'])
def demographics(msg):
    bot.send_chat_action(msg.chat.id, 'typing')
    if not msg.reply_to_message or not msg.reply_to_message.photo:
        bot.send_message(chat_id=msg.chat.id, text='Reply to photo, please!', reply_to_message_id=msg.message_id)
        return
    file_id = msg.reply_to_message.photo[-1].file_id
    faces = r.get('demogr:{}'.format(file_id))
    if faces and False:
        faces = ujson.loads(faces)
        text = create_demogr_data_str(faces)
    else:
        img_file = bot.get_file(file_id)
        img_url = FILE_URL.format(bot.token, img_file.file_path)
        image = ClImage(url=img_url)
        try:
            prediction = demogr_model.predict([image])
            if prediction['status']['code'] == 10000:
                if prediction['outputs'][0]['data'].get('regions'):
                    faces = parse_demogr_data(prediction)
                    text = create_demogr_data_str(faces)
                    r.set('demogr:{}'.format(file_id), ujson.dumps(faces))
                else:
                    bot.send_message(msg.chat.id, 'Can\'t find any faces on photo, sorry :(',
                                     reply_to_message_id=msg.message_id)
                    bot.delete_message(msg.chat.id, msg.message_id)
                    return
            else:
                bot.send_message(msg.chat.id, 'Unknown error, sorry :(', reply_to_message_id=msg.message_id)
                bot.delete_message(msg.chat.id, msg.message_id)
                return
        except Exception as e:
            print(e)
            bot.send_message(msg.chat.id, 'Unknown error, sorry :(', reply_to_message_id=msg.message_id)
            bot.delete_message(msg.chat.id, msg.message_id)
            return
    bot.send_message(msg.chat.id,
                     text=text,
                     parse_mode='HTML', reply_to_message_id=msg.reply_to_message.message_id)
    bot.delete_message(msg.chat.id, msg.message_id)


bot.skip_pending = True
bot.polling(none_stop=True)
