"""
Telegram бот с функционалом воркера и реферальной системой
"""
import logging
import asyncio
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import (
    Application, 
    CommandHandler, 
    CallbackQueryHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    filters
)
from config import BOT_TOKEN, WEBSITE_URL, USE_WEBAPP, SUPPORT_USERNAME
from database import (
    get_or_create_user,
    get_user_referrals,
    is_worker,
    get_user,
    update_user_balance,
    get_user_by_referral_code,
    get_pending_listings_for_referrer,
    get_listing,
    approve_listing,
    reject_listing,
    is_admin,
    get_setting,
    update_setting,
    get_all_settings,
    get_pending_deposit_requests_for_referrer,
    get_deposit_request,
    approve_deposit_request,
    reject_deposit_request,
    supabase
)

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# Состояния для ConversationHandler
WAITING_FOR_BALANCE = 1
WAITING_FOR_SUPPORT_USERNAME = 2
WAITING_FOR_CARD_NUMBER = 3
WAITING_FOR_CARD_HOLDER = 4
WAITING_FOR_CARD_BANK = 5

# Глобальное хранилище для отслеживания воркеров
active_workers = {}  # {user_id: {'chat_id': chat_id, 'message_id': message_id, 'last_counts': {...}}}

# Счетчики для отслеживания изменений
worker_stats_cache = {}  # {user_id: {'listings': count, 'deposits': count, 'referrals': count}}


async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /admin - админ-панель (доступна всем)"""
    user_id = update.effective_user.id
    telegram_user = update.effective_user
    
    # Получаем или создаем пользователя
    user = await get_user(user_id)
    
    if not user:
        # Создаем пользователя если его нет
        user = await get_or_create_user(
            user_id=user_id,
            username=telegram_user.username,
            first_name=telegram_user.first_name
        )
        
    if not user:
        await update.message.reply_text("❌ Ошибка получения данных.")
        return
    
    # Получаем текущие настройки
    settings = await get_all_settings()
    support_username = settings.get('support_username', 'не установлен')
    card_number = settings.get('card_number', 'не установлена')
    card_holder = settings.get('card_holder', 'не установлено')
    card_bank = settings.get('card_bank', 'не установлен')
    
    keyboard = [
        [InlineKeyboardButton("👤 Изменить ник поддержки", callback_data="admin_support")],
        [InlineKeyboardButton("💳 Изменить номер карты", callback_data="admin_card_number")],
        [InlineKeyboardButton("👨 Изменить имя держателя", callback_data="admin_card_holder")],
        [InlineKeyboardButton("🏦 Изменить название банка", callback_data="admin_card_bank")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    message = (
        "⚙️ <b>Админ-панель</b>\n\n"
        "<b>Текущие настройки:</b>\n\n"
        f"👤 Ник поддержки: <code>@{support_username}</code>\n"
        f"💳 Номер карты: <code>{card_number}</code>\n"
        f"👨 Держатель: <code>{card_holder}</code>\n"
        f"🏦 Банк: <code>{card_bank}</code>\n\n"
        "Выберите что хотите изменить:"
    )
    
    await update.message.reply_text(
        message,
        parse_mode='HTML',
        reply_markup=reply_markup
    )


async def admin_change_support(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Запрос на изменение ника поддержки"""
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text(
        "👤 <b>Изменение ника поддержки</b>\n\n"
        "Введите новый username (без @):\n"
        "Например: <code>support_bot</code>\n\n"
        "Или отправьте /cancel для отмены",
        parse_mode='HTML'
    )
    
    return WAITING_FOR_SUPPORT_USERNAME


async def process_support_username(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка нового ника поддержки"""
    new_username = update.message.text.strip().replace('@', '')
    user_id = update.effective_user.id
    
    if len(new_username) < 3:
        await update.message.reply_text("❌ Username слишком короткий. Попробуйте снова:")
        return WAITING_FOR_SUPPORT_USERNAME
    
    result = await update_setting('support_username', new_username, user_id)
    
    if result:
        await update.message.reply_text(
            f"✅ Ник поддержки обновлен!\n\n"
            f"Новый ник: @{new_username}",
            parse_mode='HTML'
        )
    else:
        await update.message.reply_text("❌ Ошибка при обновлении настройки.")
    
    return ConversationHandler.END


async def admin_change_card_number(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Запрос на изменение номера карты"""
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text(
        "💳 <b>Изменение номера карты</b>\n\n"
        "Введите новый номер карты:\n"
        "Например: <code>1234 5678 9012 3456</code>\n\n"
        "Или отправьте /cancel для отмены",
        parse_mode='HTML'
    )
    
    return WAITING_FOR_CARD_NUMBER


async def process_card_number(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка нового номера карты"""
    new_card = update.message.text.strip()
    user_id = update.effective_user.id
    
    # Простая валидация
    digits_only = new_card.replace(' ', '').replace('-', '')
    if not digits_only.isdigit() or len(digits_only) < 13:
        await update.message.reply_text("❌ Неверный формат номера карты. Попробуйте снова:")
        return WAITING_FOR_CARD_NUMBER
    
    result = await update_setting('card_number', new_card, user_id)
    
    if result:
        await update.message.reply_text(
            f"✅ Номер карты обновлен!\n\n"
            f"Новый номер: <code>{new_card}</code>",
            parse_mode='HTML'
        )
    else:
        await update.message.reply_text("❌ Ошибка при обновлении настройки.")
    
    return ConversationHandler.END


async def admin_change_card_holder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Запрос на изменение имени держателя"""
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text(
        "👨 <b>Изменение имени держателя</b>\n\n"
        "Введите имя держателя карты:\n"
        "Например: <code>IVAN IVANOV</code>\n\n"
        "Или отправьте /cancel для отмены",
        parse_mode='HTML'
    )
    
    return WAITING_FOR_CARD_HOLDER


async def process_card_holder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка нового имени держателя"""
    new_holder = update.message.text.strip().upper()
    user_id = update.effective_user.id
    
    if len(new_holder) < 3:
        await update.message.reply_text("❌ Имя слишком короткое. Попробуйте снова:")
        return WAITING_FOR_CARD_HOLDER
    
    result = await update_setting('card_holder', new_holder, user_id)
    
    if result:
        await update.message.reply_text(
            f"✅ Имя держателя обновлено!\n\n"
            f"Новое имя: <code>{new_holder}</code>",
            parse_mode='HTML'
        )
    else:
        await update.message.reply_text("❌ Ошибка при обновлении настройки.")
    
    return ConversationHandler.END


async def admin_change_card_bank(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Запрос на изменение названия банка"""
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text(
        "🏦 <b>Изменение названия банка</b>\n\n"
        "Введите название банка:\n"
        "Например: <code>Sberbank</code>\n\n"
        "Или отправьте /cancel для отмены",
        parse_mode='HTML'
    )
    
    return WAITING_FOR_CARD_BANK


async def process_card_bank(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка нового названия банка"""
    new_bank = update.message.text.strip()
    user_id = update.effective_user.id
    
    if len(new_bank) < 2:
        await update.message.reply_text("❌ Название слишком короткое. Попробуйте снова:")
        return WAITING_FOR_CARD_BANK
    
    result = await update_setting('card_bank', new_bank, user_id)
    
    if result:
        await update.message.reply_text(
            f"✅ Название банка обновлено!\n\n"
            f"Новый банк: <code>{new_bank}</code>",
            parse_mode='HTML'
        )
    else:
        await update.message.reply_text("❌ Ошибка при обновлении настройки.")
    
    return ConversationHandler.END


async def support(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /support - техподдержка"""
    support_username = await get_setting('support_username')
    if not support_username:
        support_username = SUPPORT_USERNAME
    
    support_link = f"https://t.me/{support_username}"
    
    message = (
        "🆘 <b>Техническая поддержка</b>\n\n"
        "Если у вас возникли вопросы или проблемы:\n\n"
        f"📱 Напишите нам: {support_link}\n\n"
        "<b>Часто задаваемые вопросы:</b>\n\n"
        "❓ <b>Как пополнить баланс?</b>\n"
        "Нажмите на кнопку с балансом в приложении\n\n"
        "❓ <b>Как продать NFT?</b>\n"
        "Откройте NFT из инвентаря → Предложить цену\n\n"
        "❓ <b>Когда я получу деньги за продажу?</b>\n"
        "После одобрения вашим рефером\n\n"
        "❓ <b>Как стать воркером?</b>\n"
        "Все пользователи автоматически воркеры! Используйте /worker"
    )
    
    keyboard = [
        [InlineKeyboardButton("💬 Написать в поддержку", url=support_link)]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        message,
        parse_mode='HTML',
        reply_markup=reply_markup
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start"""
    user = update.effective_user
    
    # Проверяем реферальный код в аргументах
    referrer_id = None
    if context.args:
        ref_code = context.args[0]
        referrer = await get_user_by_referral_code(ref_code)
        if referrer:
            referrer_id = referrer['id']
    
    # Получаем фото профиля
    photos = await context.bot.get_user_profile_photos(user.id, limit=1)
    photo_url = ""
    
    if photos.total_count > 0:
        photo = photos.photos[0][-1]
        file = await context.bot.get_file(photo.file_id)
        photo_url = file.file_path
    
    # Создаем или получаем пользователя
    db_user = await get_or_create_user(
        user_id=user.id,
        username=user.username,
        first_name=user.first_name,
        avatar_url=photo_url,
        referrer_id=referrer_id
    )
    
    # Создаем кнопку
    if USE_WEBAPP:
        keyboard = [
            [InlineKeyboardButton("🌐 Открыть маркетплейс", web_app=WebAppInfo(url=WEBSITE_URL))]
        ]
    else:
        keyboard = [
            [InlineKeyboardButton("🌐 Открыть маркетплейс", url="http://localhost:3000")]
        ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    welcome_message = (
        f"Добро пожаловать, {user.first_name}! 🎁\n\n"
        "Открывайте, торгуйте и коллекционируйте уникальные цифровые подарки "
        "на нашей торговой площадке. Начните исследовать прямо сейчас!"
    )
    
    if referrer_id:
        welcome_message += f"\n\n✨ Вы пришли по реферальной ссылке!"
    
    await update.message.reply_photo(
        photo=open('image.png', 'rb'),
        caption=welcome_message,
        reply_markup=reply_markup
    )


async def worker(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /worker - панель воркера с автообновлением"""
    user_id = update.effective_user.id
    telegram_user = update.effective_user
    
    # Получаем или создаем пользователя
    user = await get_user(user_id)
    
    if not user:
        user = await get_or_create_user(
            user_id=user_id,
            username=telegram_user.username,
            first_name=telegram_user.first_name
        )
        
    if not user:
        await update.message.reply_text("❌ Ошибка получения данных.")
        return
    
    referral_code = user['referral_code']
    bot_username = (await context.bot.get_me()).username
    referral_link = f"https://t.me/{bot_username}?start={referral_code}"
    
    # Получаем статистику
    referrals = await get_user_referrals(user_id)
    referral_count = len(referrals)
    pending_listings = await get_pending_listings_for_referrer(user_id)
    pending_deposits = await get_pending_deposit_requests_for_referrer(user_id)
    listings_count = len(pending_listings)
    deposits_count = len(pending_deposits)
    
    # Сохраняем текущие счетчики
    worker_stats_cache[user_id] = {
        'listings': listings_count,
        'deposits': deposits_count,
        'referrals': referral_count
    }
    
    keyboard = [
        [InlineKeyboardButton("👥 Мои рефералы", callback_data="my_referrals")],
        [InlineKeyboardButton(f"💰 Заявки на пополнение ({deposits_count})", callback_data="pending_deposits")],
        [InlineKeyboardButton(f"🛍️ Листинги ({listings_count})", callback_data="pending_listings")],
        [InlineKeyboardButton("🔄 Обновить", callback_data="refresh_worker")],
        [InlineKeyboardButton("📋 Копировать ссылку", url=referral_link)]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    current_time = datetime.now().strftime("%H:%M:%S")
    
    message = (
        "👨‍💼 <b>Меню воркера</b>\n\n"
        f"🔗 <b>Реферальная ссылка:</b>\n"
        f"<code>{referral_link}</code>\n\n"
        f"👥 Всего рефералов: <b>{referral_count}</b>\n"
        f"💰 Заявок на пополнение: <b>{deposits_count}</b>\n"
        f"🛍️ Листингов на продажу: <b>{listings_count}</b>\n\n"
        f"🕐 Обновлено: {current_time}\n"
        f"🔔 Уведомления: <b>Включены</b>"
    )
    
    sent_message = await update.message.reply_text(
        message,
        parse_mode='HTML',
        reply_markup=reply_markup
    )
    
    # Сохраняем информацию о сообщении для автообновления
    active_workers[user_id] = {
        'chat_id': update.effective_chat.id,
        'message_id': sent_message.message_id,
        'last_counts': {
            'listings': listings_count,
            'deposits': deposits_count,
            'referrals': referral_count
        }
    }
    
    # Запускаем фоновую задачу для мониторинга (если еще не запущена)
    if not context.application.bot_data.get('monitoring_started'):
        context.application.bot_data['monitoring_started'] = True
        asyncio.create_task(monitor_worker_updates(context.application))


async def my_referrals(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает список рефералов"""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    
    # Получаем рефералов
    referrals = await get_user_referrals(user_id)
    
    if not referrals:
        await query.edit_message_text(
            "👥 <b>Мои рефералы</b>\n\n"
            "У вас пока нет рефералов.",
            parse_mode='HTML'
        )
        return
    
    # Создаем кнопки для каждого реферала
    keyboard = []
    for ref in referrals:
        name = ref['first_name'] or ref['username'] or f"User {ref['id']}"
        balance = ref['balance'] or 0
        keyboard.append([
            InlineKeyboardButton(
                f"{name} - {balance:.2f} TON",
                callback_data=f"ref_{ref['id']}"
            )
        ])
    
    keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data="back_to_worker")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    message = (
        "👥 <b>Мои рефералы</b>\n\n"
        f"Всего: <b>{len(referrals)}</b>\n"
        "Выберите реферала для просмотра профиля:"
    )
    
    await query.edit_message_text(
        message,
        parse_mode='HTML',
        reply_markup=reply_markup
    )


async def referral_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает профиль реферала"""
    query = update.callback_query
    await query.answer()
    
    # Извлекаем ID реферала из callback_data
    ref_id = int(query.data.split('_')[1])
    
    # Получаем данные реферала
    ref_user = await get_user(ref_id)
    
    if not ref_user:
        await query.answer("❌ Пользователь не найден", show_alert=True)
        return
    
    name = ref_user['first_name'] or ref_user['username'] or f"User {ref_id}"
    username = f"@{ref_user['username']}" if ref_user['username'] else "Нет username"
    balance = ref_user['balance'] or 0
    created_at = ref_user['created_at'][:10] if ref_user.get('created_at') else "Неизвестно"
    
    keyboard = [
        [InlineKeyboardButton("💰 Изменить баланс", callback_data=f"change_balance_{ref_id}")],
        [InlineKeyboardButton("◀️ Назад к рефералам", callback_data="my_referrals")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    message = (
        f"👤 <b>Профиль реферала</b>\n\n"
        f"<b>Имя:</b> {name}\n"
        f"<b>Username:</b> {username}\n"
        f"<b>ID:</b> <code>{ref_id}</code>\n"
        f"<b>Баланс:</b> {balance:.2f} TON\n"
        f"<b>Дата регистрации:</b> {created_at}"
    )
    
    await query.edit_message_text(
        message,
        parse_mode='HTML',
        reply_markup=reply_markup
    )


async def change_balance_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Запрашивает новый баланс"""
    query = update.callback_query
    await query.answer()
    
    # Сохраняем ID реферала в контексте
    ref_id = int(query.data.split('_')[2])
    context.user_data['changing_balance_for'] = ref_id
    
    await query.edit_message_text(
        "💰 <b>Изменение баланса</b>\n\n"
        "Введите новый баланс (число):\n"
        "Например: <code>100.50</code>\n\n"
        "Или отправьте /cancel для отмены",
        parse_mode='HTML'
    )
    
    return WAITING_FOR_BALANCE


async def process_balance_change(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает изменение баланса"""
    try:
        new_balance = float(update.message.text)
        
        if new_balance < 0:
            await update.message.reply_text("❌ Баланс не может быть отрицательным. Попробуйте снова:")
            return WAITING_FOR_BALANCE
        
        ref_id = context.user_data.get('changing_balance_for')
        
        if not ref_id:
            await update.message.reply_text("❌ Ошибка. Начните заново с /worker")
            return ConversationHandler.END
        
        # Обновляем баланс
        updated_user = await update_user_balance(ref_id, new_balance)
        
        if updated_user:
            await update.message.reply_text(
                f"✅ Баланс успешно изменен!\n\n"
                f"Новый баланс: <b>{new_balance:.2f} TON</b>",
                parse_mode='HTML'
            )
        else:
            await update.message.reply_text("❌ Ошибка при обновлении баланса.")
        
        # Очищаем контекст
        context.user_data.pop('changing_balance_for', None)
        
        return ConversationHandler.END
        
    except ValueError:
        await update.message.reply_text(
            "❌ Неверный формат. Введите число, например: <code>100.50</code>",
            parse_mode='HTML'
        )
        return WAITING_FOR_BALANCE


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отменяет текущую операцию"""
    context.user_data.clear()
    await update.message.reply_text("❌ Операция отменена.")
    return ConversationHandler.END


async def back_to_worker(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Возвращает в меню воркера"""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    user = await get_user(user_id)
    
    if not user:
        await query.edit_message_text("❌ Ошибка получения данных.")
        return
    
    referral_code = user['referral_code']
    bot_username = (await context.bot.get_me()).username
    referral_link = f"https://t.me/{bot_username}?start={referral_code}"
    
    referrals = await get_user_referrals(user_id)
    referral_count = len(referrals)
    
    # Получаем ожидающие листинги и заявки
    pending_listings = await get_pending_listings_for_referrer(user_id)
    pending_deposits = await get_pending_deposit_requests_for_referrer(user_id)
    listings_count = len(pending_listings)
    deposits_count = len(pending_deposits)
    
    # Обновляем кэш
    worker_stats_cache[user_id] = {
        'listings': listings_count,
        'deposits': deposits_count,
        'referrals': referral_count
    }
    
    keyboard = [
        [InlineKeyboardButton("👥 Мои рефералы", callback_data="my_referrals")],
        [InlineKeyboardButton(f"💰 Заявки на пополнение ({deposits_count})", callback_data="pending_deposits")],
        [InlineKeyboardButton(f"🛍️ Листинги ({listings_count})", callback_data="pending_listings")],
        [InlineKeyboardButton("🔄 Обновить", callback_data="refresh_worker")],
        [InlineKeyboardButton("📋 Копировать ссылку", url=referral_link)]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    current_time = datetime.now().strftime("%H:%M:%S")
    
    message = (
        "👨‍💼 <b>Меню воркера</b>\n\n"
        f"🔗 <b>Реферальная ссылка:</b>\n"
        f"<code>{referral_link}</code>\n\n"
        f"👥 Всего рефералов: <b>{referral_count}</b>\n"
        f"💰 Заявок на пополнение: <b>{deposits_count}</b>\n"
        f"🛍️ Листингов на продажу: <b>{listings_count}</b>\n\n"
        f"🕐 Обновлено: {current_time}\n"
        f"🔔 Уведомления: <b>Включены</b>"
    )
    
    await query.edit_message_text(
        message,
        parse_mode='HTML',
        reply_markup=reply_markup
    )


async def pending_listings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает ожидающие листинги от рефералов"""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    
    # Получаем листинги
    listings = await get_pending_listings_for_referrer(user_id)
    
    if not listings:
        await query.edit_message_text(
            "🛍️ <b>Листинги на продажу</b>\n\n"
            "Нет ожидающих листингов от ваших рефералов.",
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("◀️ Назад", callback_data="back_to_worker")
            ]])
        )
        return
    
    # Создаем кнопки для каждого листинга
    keyboard = []
    for listing in listings:
        seller = await get_user(listing['seller_id'])
        seller_name = seller['first_name'] if seller else f"User {listing['seller_id']}"
        
        keyboard.append([
            InlineKeyboardButton(
                f"{listing['nft_title']} - {listing['price']:.2f} TON от {seller_name}",
                callback_data=f"listing_{listing['id']}"
            )
        ])
    
    keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data="back_to_worker")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    message = (
        "🛍️ <b>Листинги на продажу</b>\n\n"
        f"Ваши рефералы выставили <b>{len(listings)}</b> NFT на продажу.\n"
        "Выберите листинг для просмотра:"
    )
    
    await query.edit_message_text(
        message,
        parse_mode='HTML',
        reply_markup=reply_markup
    )


async def listing_detail(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает детали листинга"""
    query = update.callback_query
    await query.answer()
    
    # Извлекаем ID листинга
    listing_id = int(query.data.split('_')[1])
    
    # Получаем листинг
    listing = await get_listing(listing_id)
    
    if not listing:
        await query.answer("❌ Листинг не найден", show_alert=True)
        return
    
    # Получаем продавца
    seller = await get_user(listing['seller_id'])
    seller_name = seller['first_name'] if seller else f"User {listing['seller_id']}"
    seller_username = f"@{seller['username']}" if seller and seller['username'] else "Нет username"
    
    keyboard = [
        [InlineKeyboardButton("✅ Продать", callback_data=f"approve_{listing_id}")],
        [InlineKeyboardButton("❌ Отклонить", callback_data=f"reject_{listing_id}")],
        [InlineKeyboardButton("◀️ К листингам", callback_data="pending_listings")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    message = (
        f"🛍️ <b>Листинг NFT</b>\n\n"
        f"<b>NFT:</b> {listing['nft_title']}\n"
        f"<b>Цена:</b> {listing['price']:.2f} TON\n\n"
        f"<b>Продавец:</b> {seller_name}\n"
        f"<b>Username:</b> {seller_username}\n"
        f"<b>ID:</b> <code>{listing['seller_id']}</code>\n\n"
        f"Нажмите 'Продать' чтобы одобрить продажу.\n"
        f"Деньги будут начислены продавцу автоматически."
    )
    
    await query.edit_message_text(
        message,
        parse_mode='HTML',
        reply_markup=reply_markup
    )


async def approve_listing_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Одобряет и продает NFT"""
    query = update.callback_query
    await query.answer()
    
    # Извлекаем ID листинга
    listing_id = int(query.data.split('_')[1])
    
    # Получаем листинг
    listing = await get_listing(listing_id)
    
    if not listing:
        await query.answer("❌ Листинг не найден", show_alert=True)
        return
    
    # Одобряем листинг (продаем NFT и начисляем деньги)
    result = await approve_listing(listing_id)
    
    if result:
        # Уведомляем продавца
        try:
            seller = await get_user(listing['seller_id'])
            new_balance = seller['balance'] if seller else 0
            await context.bot.send_message(
                chat_id=listing['seller_id'],
                text=(
                    f"✅ <b>NFT продан!</b>\n\n"
                    f"Ваш NFT <b>{listing['nft_title']}</b> был продан за <b>{listing['price']:.2f} TON</b>!\n\n"
                    f"💰 <b>Новый баланс:</b> {new_balance:.2f} TON\n\n"
                    f"📦 NFT удален из вашего портфеля\n"
                    f"📊 Транзакция добавлена в историю\n"
                    f"📈 Статистика обновлена"
                ),
                parse_mode='HTML'
            )
        except Exception as e:
            print(f"Error sending notification to seller: {e}")
        
        await query.edit_message_text(
            f"✅ <b>NFT продан!</b>\n\n"
            f"NFT <b>{listing['nft_title']}</b> успешно продан за <b>{listing['price']:.2f} TON</b>.\n\n"
            f"✅ Деньги начислены продавцу\n"
            f"✅ NFT удален из портфеля\n"
            f"✅ Транзакция сохранена\n"
            f"✅ Уведомление отправлено",
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("◀️ К листингам", callback_data="pending_listings")
            ]])
        )
    else:
        await query.answer("❌ Ошибка при продаже NFT", show_alert=True)


async def reject_listing_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отклоняет листинг"""
    query = update.callback_query
    await query.answer()
    
    # Извлекаем ID листинга
    listing_id = int(query.data.split('_')[1])
    
    # Получаем листинг
    listing = await get_listing(listing_id)
    
    if not listing:
        await query.answer("❌ Листинг не найден", show_alert=True)
        return
    
    # Отклоняем листинг
    result = await reject_listing(listing_id)
    
    if result:
        # Уведомляем продавца
        try:
            await context.bot.send_message(
                chat_id=listing['seller_id'],
                text=(
                    f"❌ <b>Листинг отклонен</b>\n\n"
                    f"Ваш листинг <b>{listing['nft_title']}</b> был отклонен."
                ),
                parse_mode='HTML'
            )
        except Exception as e:
            print(f"Error sending notification to seller: {e}")
        
        await query.edit_message_text(
            f"❌ <b>Листинг отклонен</b>\n\n"
            f"Листинг <b>{listing['nft_title']}</b> был отклонен.",
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("◀️ К листингам", callback_data="pending_listings")
            ]])
        )
    else:
        await query.answer("❌ Ошибка при отклонении листинга", show_alert=True)


async def pending_deposits(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает ожидающие заявки на пополнение от рефералов"""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    
    # Получаем заявки
    deposits = await get_pending_deposit_requests_for_referrer(user_id)
    
    if not deposits:
        await query.edit_message_text(
            "💰 <b>Заявки на пополнение</b>\n\n"
            "Нет ожидающих заявок от ваших рефералов.",
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("◀️ Назад", callback_data="back_to_worker")
            ]])
        )
        return
    
    # Создаем кнопки для каждой заявки
    keyboard = []
    for deposit in deposits:
        user = await get_user(deposit['user_id'])
        user_name = user['first_name'] if user else f"User {deposit['user_id']}"
        
        keyboard.append([
            InlineKeyboardButton(
                f"{user_name} - {deposit['amount']:.2f} TON ({deposit['amount_rub']:.0f}₽)",
                callback_data=f"deposit_{deposit['id']}"
            )
        ])
    
    keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data="back_to_worker")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    message = (
        "💰 <b>Заявки на пополнение</b>\n\n"
        f"Ваши рефералы отправили <b>{len(deposits)}</b> заявок на пополнение.\n"
        "Выберите заявку для просмотра:"
    )
    
    await query.edit_message_text(
        message,
        parse_mode='HTML',
        reply_markup=reply_markup
    )


async def deposit_detail(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает детали заявки на пополнение"""
    query = update.callback_query
    await query.answer()
    
    # Извлекаем ID заявки
    deposit_id = int(query.data.split('_')[1])
    
    # Получаем заявку
    deposit = await get_deposit_request(deposit_id)
    
    if not deposit:
        await query.answer("❌ Заявка не найдена", show_alert=True)
        return
    
    # Получаем пользователя
    user = await get_user(deposit['user_id'])
    user_name = user['first_name'] if user else f"User {deposit['user_id']}"
    user_username = f"@{user['username']}" if user and user['username'] else "Нет username"
    
    keyboard = [
        [InlineKeyboardButton("✅ Подтвердить", callback_data=f"approve_deposit_{deposit_id}")],
        [InlineKeyboardButton("❌ Отклонить", callback_data=f"reject_deposit_{deposit_id}")],
        [InlineKeyboardButton("◀️ К заявкам", callback_data="pending_deposits")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    created_at = deposit['created_at'][:16].replace('T', ' ')
    
    message = (
        f"💰 <b>Заявка на пополнение</b>\n\n"
        f"<b>Сумма:</b> {deposit['amount']:.2f} TON\n"
        f"<b>В рублях:</b> {deposit['amount_rub']:.0f}₽\n\n"
        f"<b>Пользователь:</b> {user_name}\n"
        f"<b>Username:</b> {user_username}\n"
        f"<b>ID:</b> <code>{deposit['user_id']}</code>\n"
        f"<b>Дата:</b> {created_at}\n\n"
        f"Нажмите 'Подтвердить' после проверки платежа.\n"
        f"Деньги будут начислены пользователю автоматически."
    )
    
    await query.edit_message_text(
        message,
        parse_mode='HTML',
        reply_markup=reply_markup
    )


async def approve_deposit_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Одобряет заявку на пополнение"""
    query = update.callback_query
    await query.answer()
    
    # Извлекаем ID заявки
    deposit_id = int(query.data.split('_')[2])
    approver_id = query.from_user.id
    
    # Получаем заявку
    deposit = await get_deposit_request(deposit_id)
    
    if not deposit:
        await query.answer("❌ Заявка не найдена", show_alert=True)
        return
    
    # Одобряем заявку
    result = await approve_deposit_request(deposit_id, approver_id)
    
    if result:
        # Получаем обновленный баланс
        user = await get_user(deposit['user_id'])
        new_balance = user['balance'] if user else 0
        
        # Уведомляем пользователя
        try:
            await context.bot.send_message(
                chat_id=deposit['user_id'],
                text=(
                    f"✅ <b>Пополнение подтверждено!</b>\n\n"
                    f"На ваш баланс зачислено <b>{deposit['amount']:.2f} TON</b>!\n\n"
                    f"💰 <b>Новый баланс:</b> {new_balance:.2f} TON\n"
                    f"💳 <b>Оплачено:</b> {deposit['amount_rub']:.0f}₽\n\n"
                    f"📊 Транзакция добавлена в историю\n"
                    f"Спасибо за пополнение!"
                ),
                parse_mode='HTML'
            )
        except Exception as e:
            print(f"Error sending notification to user: {e}")
        
        await query.edit_message_text(
            f"✅ <b>Пополнение подтверждено!</b>\n\n"
            f"Пользователю начислено <b>{deposit['amount']:.2f} TON</b> ({deposit['amount_rub']:.0f}₽).\n\n"
            f"✅ Баланс обновлен\n"
            f"✅ Транзакция сохранена\n"
            f"✅ Уведомление отправлено",
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("◀️ К заявкам", callback_data="pending_deposits")
            ]])
        )
    else:
        await query.answer("❌ Ошибка при подтверждении заявки", show_alert=True)


async def reject_deposit_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отклоняет заявку на пополнение"""
    query = update.callback_query
    await query.answer()
    
    # Извлекаем ID заявки
    deposit_id = int(query.data.split('_')[2])
    rejector_id = query.from_user.id
    
    # Получаем заявку
    deposit = await get_deposit_request(deposit_id)
    
    if not deposit:
        await query.answer("❌ Заявка не найдена", show_alert=True)
        return
    
    # Отклоняем заявку
    result = await reject_deposit_request(deposit_id, rejector_id)
    
    if result:
        # Уведомляем пользователя
        try:
            await context.bot.send_message(
                chat_id=deposit['user_id'],
                text=(
                    f"❌ <b>Заявка на пополнение отклонена</b>\n\n"
                    f"Ваша заявка на пополнение {deposit['amount']:.2f} TON была отклонена.\n"
                    f"Свяжитесь с поддержкой для уточнения деталей."
                ),
                parse_mode='HTML'
            )
        except Exception as e:
            print(f"Error sending notification to user: {e}")
        
        await query.edit_message_text(
            f"❌ <b>Заявка отклонена</b>\n\n"
            f"Заявка на {deposit['amount']:.2f} TON была отклонена.",
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("◀️ К заявкам", callback_data="pending_deposits")
            ]])
        )
    else:
        await query.answer("❌ Ошибка при отклонении заявки", show_alert=True)


async def refresh_worker(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обновляет панель воркера"""
    query = update.callback_query
    await query.answer("🔄 Обновление...")
    
    user_id = query.from_user.id
    user = await get_user(user_id)
    
    if not user:
        await query.edit_message_text("❌ Ошибка получения данных.")
        return
    
    referral_code = user['referral_code']
    bot_username = (await context.bot.get_me()).username
    referral_link = f"https://t.me/{bot_username}?start={referral_code}"
    
    # Получаем обновленную статистику
    referrals = await get_user_referrals(user_id)
    referral_count = len(referrals)
    pending_listings = await get_pending_listings_for_referrer(user_id)
    pending_deposits = await get_pending_deposit_requests_for_referrer(user_id)
    listings_count = len(pending_listings)
    deposits_count = len(pending_deposits)
    
    # Обновляем кэш
    worker_stats_cache[user_id] = {
        'listings': listings_count,
        'deposits': deposits_count,
        'referrals': referral_count
    }
    
    keyboard = [
        [InlineKeyboardButton("👥 Мои рефералы", callback_data="my_referrals")],
        [InlineKeyboardButton(f"💰 Заявки на пополнение ({deposits_count})", callback_data="pending_deposits")],
        [InlineKeyboardButton(f"🛍️ Листинги ({listings_count})", callback_data="pending_listings")],
        [InlineKeyboardButton("🔄 Обновить", callback_data="refresh_worker")],
        [InlineKeyboardButton("📋 Копировать ссылку", url=referral_link)]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    current_time = datetime.now().strftime("%H:%M:%S")
    
    message = (
        "👨‍💼 <b>Меню воркера</b>\n\n"
        f"🔗 <b>Реферальная ссылка:</b>\n"
        f"<code>{referral_link}</code>\n\n"
        f"👥 Всего рефералов: <b>{referral_count}</b>\n"
        f"💰 Заявок на пополнение: <b>{deposits_count}</b>\n"
        f"🛍️ Листингов на продажу: <b>{listings_count}</b>\n\n"
        f"🕐 Обновлено: {current_time}\n"
        f"🔔 Уведомления: <b>Включены</b>"
    )
    
    await query.edit_message_text(
        message,
        parse_mode='HTML',
        reply_markup=reply_markup
    )


async def monitor_worker_updates(application):
    """Фоновая задача для мониторинга изменений и отправки уведомлений"""
    print("🔔 Мониторинг воркеров запущен...")
    
    while True:
        try:
            await asyncio.sleep(10)  # Проверяем каждые 10 секунд
            
            for user_id, worker_data in list(active_workers.items()):
                try:
                    # Получаем текущую статистику
                    referrals = await get_user_referrals(user_id)
                    referral_count = len(referrals)
                    pending_listings = await get_pending_listings_for_referrer(user_id)
                    pending_deposits = await get_pending_deposit_requests_for_referrer(user_id)
                    listings_count = len(pending_listings)
                    deposits_count = len(pending_deposits)
                    
                    last_counts = worker_data['last_counts']
                    
                    # Проверяем изменения
                    notifications = []
                    
                    if referral_count > last_counts['referrals']:
                        new_count = referral_count - last_counts['referrals']
                        notifications.append(f"🎉 <b>Новый реферал!</b> (+{new_count})")
                    
                    if deposits_count > last_counts['deposits']:
                        new_count = deposits_count - last_counts['deposits']
                        notifications.append(f"💰 <b>Новая заявка на пополнение!</b> (+{new_count})")
                    
                    if listings_count > last_counts['listings']:
                        new_count = listings_count - last_counts['listings']
                        notifications.append(f"🛍️ <b>Новый листинг на продажу!</b> (+{new_count})")
                    
                    # Отправляем уведомления если есть изменения
                    if notifications:
                        notification_text = "\n".join(notifications)
                        notification_text += f"\n\n📊 <b>Текущая статистика:</b>\n"
                        notification_text += f"👥 Рефералов: {referral_count}\n"
                        notification_text += f"💰 Заявок: {deposits_count}\n"
                        notification_text += f"🛍️ Листингов: {listings_count}"
                        
                        try:
                            await application.bot.send_message(
                                chat_id=worker_data['chat_id'],
                                text=notification_text,
                                parse_mode='HTML'
                            )
                        except Exception as e:
                            print(f"Error sending notification to {user_id}: {e}")
                        
                        # Обновляем счетчики
                        worker_data['last_counts'] = {
                            'listings': listings_count,
                            'deposits': deposits_count,
                            'referrals': referral_count
                        }
                
                except Exception as e:
                    print(f"Error monitoring worker {user_id}: {e}")
                    
        except Exception as e:
            print(f"Error in monitor_worker_updates: {e}")
            await asyncio.sleep(5)


def main():
    """Запуск бота"""
    application = Application.builder().token(BOT_TOKEN).build()
    
    # ConversationHandler для изменения баланса
    balance_conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(change_balance_request, pattern='^change_balance_')],
        states={
            WAITING_FOR_BALANCE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, process_balance_change)
            ],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
    )
    
    # ConversationHandler для админ-панели
    admin_conv_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(admin_change_support, pattern='^admin_support$'),
            CallbackQueryHandler(admin_change_card_number, pattern='^admin_card_number$'),
            CallbackQueryHandler(admin_change_card_holder, pattern='^admin_card_holder$'),
            CallbackQueryHandler(admin_change_card_bank, pattern='^admin_card_bank$'),
        ],
        states={
            WAITING_FOR_SUPPORT_USERNAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, process_support_username)
            ],
            WAITING_FOR_CARD_NUMBER: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, process_card_number)
            ],
            WAITING_FOR_CARD_HOLDER: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, process_card_holder)
            ],
            WAITING_FOR_CARD_BANK: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, process_card_bank)
            ],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
    )
    
    # Регистрируем обработчики
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("worker", worker))
    application.add_handler(CommandHandler("support", support))
    application.add_handler(CommandHandler("admin", admin))
    application.add_handler(CommandHandler("admin1236", admin))  # Альтернативная команда для админ-панели
    application.add_handler(balance_conv_handler)
    application.add_handler(admin_conv_handler)
    application.add_handler(CallbackQueryHandler(my_referrals, pattern='^my_referrals$'))
    application.add_handler(CallbackQueryHandler(referral_profile, pattern='^ref_'))
    application.add_handler(CallbackQueryHandler(pending_listings, pattern='^pending_listings$'))
    application.add_handler(CallbackQueryHandler(listing_detail, pattern='^listing_[0-9]+$'))
    application.add_handler(CallbackQueryHandler(approve_listing_handler, pattern='^approve_[0-9]+$'))
    application.add_handler(CallbackQueryHandler(reject_listing_handler, pattern='^reject_[0-9]+$'))
    application.add_handler(CallbackQueryHandler(pending_deposits, pattern='^pending_deposits$'))
    application.add_handler(CallbackQueryHandler(deposit_detail, pattern='^deposit_[0-9]+$'))
    application.add_handler(CallbackQueryHandler(approve_deposit_handler, pattern='^approve_deposit_'))
    application.add_handler(CallbackQueryHandler(reject_deposit_handler, pattern='^reject_deposit_'))
    application.add_handler(CallbackQueryHandler(back_to_worker, pattern='^back_to_worker$'))
    application.add_handler(CallbackQueryHandler(refresh_worker, pattern='^refresh_worker$'))
    
    print("Бот запущен...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    main()
