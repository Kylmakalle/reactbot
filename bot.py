import os

import redis
import telebot
import ujson
from telebot.types import InlineKeyboardButton, InlineKeyboardMarkup
from collections import namedtuple

UserIDs = namedtuple('UserIDs', ['id', 'counts'])

token = os.environ['TELEGRAM_TOKEN']
r = redis.from_url(os.environ.get("REDIS_URL"))
bot = telebot.TeleBot(token)


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

        text += '({} - {}, {} - {})'.format('❤️', user_info['count_label_1'], '💔',
                                            user_info['count_label_2'])
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
            text += '<b>{}.</b> {} ({} - {}, {} - {})\n'.format(usr + 1, user_name, '❤️', labels_list[0], '💔',
                                                                labels_list[1])

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


bot.skip_pending = True
bot.polling(none_stop=True)
