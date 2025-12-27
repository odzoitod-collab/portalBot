import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import Application, CommandHandler, ContextTypes

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# Замените на ваш токен бота
BOT_TOKEN = '7256264140:AAF0Ons2xjoc7ljB62VR2s-85bHIKdC_D2Y'

# Для Web App нужен HTTPS URL
# Вариант 1: Используйте ngrok (ngrok http 3000) и вставьте HTTPS URL
# Вариант 2: Разместите на хостинге с HTTPS
WEBSITE_URL = 'https://4931efd76f90.ngrok-free.app/'  # Ваш ngrok URL

# Используем Web App для передачи данных пользователя
USE_WEBAPP = True

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start"""
    
    user = update.effective_user
    
    # Получаем данные пользователя
    user_id = user.id
    username = user.username or user.first_name or "User"
    first_name = user.first_name or ""
    last_name = user.last_name or ""
    
    # Получаем фото профиля пользователя
    photos = await context.bot.get_user_profile_photos(user_id, limit=1)
    photo_url = ""
    
    if photos.total_count > 0:
        # Получаем самое большое фото
        photo = photos.photos[0][-1]
        file = await context.bot.get_file(photo.file_id)
        photo_url = file.file_path
    
    # Создаем кнопку
    if USE_WEBAPP:
        # Web App кнопка (требует HTTPS)
        keyboard = [
            [InlineKeyboardButton("🌐 Открыть маркетплейс", web_app=WebAppInfo(url=WEBSITE_URL))]
        ]
    else:
        # Обычная кнопка с URL (для тестирования)
        keyboard = [
            [InlineKeyboardButton("🌐 Открыть маркетплейс", url="http://localhost:3000")]
        ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Приветственное сообщение на русском
    welcome_message = (
        f"Добро пожаловать, {first_name}! 🎁\n\n"
        "Открывайте, торгуйте и коллекционируйте уникальные цифровые подарки "
        "на нашей торговой площадке. Начните исследовать прямо сейчас!"
    )
    
    # Отправляем фото с сообщением и кнопкой
    await update.message.reply_photo(
        photo=open('image.png', 'rb'),
        caption=welcome_message,
        reply_markup=reply_markup
    )

def main():
    """Запуск бота"""
    # Создаем приложение
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Регистрируем обработчик команды /start
    application.add_handler(CommandHandler("start", start))
    
    # Запускаем бота
    print("Бот запущен...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
