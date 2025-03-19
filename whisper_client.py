import os
import whisper
import requests
from telegram import Update
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters
from requests.auth import HTTPBasicAuth


# Загружаем модель Whisper
def transcribe_audio(uploaded_file_path, model_name='base'):
    model = whisper.load_model(model_name)
    try:
        # Транскрибируем аудиофайл
        result = model.transcribe(uploaded_file_path)
        return result["text"]
    except Exception as e:
        return f'Error during transcription: {str(e)}'


# Скачиваем голосовое сообщение из Telegram
def download_voice_message(file_id, bot):
    # Получаем информацию о файле
    file_info = bot.get_file(file_id)
    file_path = file_info.file_path
    file_name = "voice_message.ogg"  # Сохраним как OGG файл

    # Скачиваем файл
    response = requests.get(f"https://api.telegram.org/file/bot{bot.token}/{file_path}")
    with open(file_name, 'wb') as f:
        f.write(response.content)

    return file_name


# Обработчик для голосовых сообщений
def handle_voice(update: Update, context):
    # Получаем объект голосового сообщения
    voice = update.message.voice
    file_id = voice.file_id

    # Скачиваем голосовое сообщение
    voice_file = download_voice_message(file_id, context.bot)
    print(f"Downloaded file: {voice_file}")

    # Транскрибируем аудиофайл
    transcribed_text = transcribe_audio(voice_file)

    # Отправляем результат обратно в чат
    update.message.reply_text(f"Транскрибированный текст: {transcribed_text}")


# Основной метод для запуска бота
def main():
    # Токен твоего бота
    token = 'YOUR_BOT_TOKEN'

    updater = Updater(token, use_context=True)
    dp = updater.dispatcher

    # Обработчик голосовых сообщений
    dp.add_handler(MessageHandler(Filters.voice, handle_voice))

    # Запуск бота
    updater.start_polling()
    updater.idle()


if __name__ == '__main__':
    main()
