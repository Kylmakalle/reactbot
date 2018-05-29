import os

import redis
import telebot
import ujson
from telebot.types import InlineKeyboardButton, InlineKeyboardMarkup

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
    name = '<b>{}</b>'.format(msg.from_user.first_name)
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


bot.skip_pending = True
bot.polling(none_stop=True)
