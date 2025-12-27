-- ============================================
-- ФИНАЛЬНАЯ ПОЛНАЯ НАСТРОЙКА БАЗЫ ДАННЫХ
-- Portal Market - NFT Marketplace
-- ============================================
-- 
-- Этот скрипт создает ВСЕ необходимые таблицы и настройки
-- Выполните его в SQL Editor вашего Supabase проекта
-- 
-- ⚠️ ВАЖНО: Скрипт безопасен для повторного выполнения!
-- Все операции проверяют существование объектов
-- Можно запускать несколько раз без ошибок
-- 
-- ============================================

-- ============================================
-- ОПЦИОНАЛЬНО: Удаление старых таблиц
-- ============================================
-- Раскомментируйте если хотите начать с чистого листа
/*
DROP TABLE IF EXISTS deposit_requests CASCADE;
DROP TABLE IF EXISTS user_nfts CASCADE;
DROP TABLE IF EXISTS transactions CASCADE;
DROP TABLE IF EXISTS nft_listings CASCADE;
DROP TABLE IF EXISTS admins CASCADE;
DROP TABLE IF EXISTS system_settings CASCADE;
DROP TABLE IF EXISTS users CASCADE;
DROP FUNCTION IF EXISTS update_updated_at_column() CASCADE;
*/

-- ============================================
-- ТАБЛИЦА 1: Пользователи (users)
-- ============================================
CREATE TABLE IF NOT EXISTS users (
    id BIGINT PRIMARY KEY,  -- Telegram user ID
    username TEXT,
    first_name TEXT,
    avatar_url TEXT,
    balance DECIMAL(10, 2) DEFAULT 0 NOT NULL,
    referrer_id BIGINT,  -- Внешний ключ добавим позже
    referral_code TEXT UNIQUE NOT NULL,
    created_at TIMESTAMP DEFAULT NOW() NOT NULL,
    updated_at TIMESTAMP DEFAULT NOW() NOT NULL
);

-- Добавляем внешний ключ для рефералов (после создания таблицы)
DO $$ 
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'fk_users_referrer'
    ) THEN
        ALTER TABLE users 
        ADD CONSTRAINT fk_users_referrer 
        FOREIGN KEY (referrer_id) 
        REFERENCES users(id) 
        ON DELETE SET NULL;
    END IF;
END $$;

-- Индексы для users
CREATE INDEX IF NOT EXISTS idx_users_referrer ON users(referrer_id);
CREATE INDEX IF NOT EXISTS idx_users_referral_code ON users(referral_code);

-- ============================================
-- ТАБЛИЦА 2: Листинги NFT (nft_listings)
-- ============================================
CREATE TABLE IF NOT EXISTS nft_listings (
    id SERIAL PRIMARY KEY,
    nft_id TEXT NOT NULL,
    nft_title TEXT NOT NULL,
    nft_image TEXT,
    seller_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    price DECIMAL(10, 2) NOT NULL,
    status TEXT DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'rejected', 'sold')),
    created_at TIMESTAMP DEFAULT NOW() NOT NULL,
    updated_at TIMESTAMP DEFAULT NOW() NOT NULL
);

-- Индексы для nft_listings
CREATE INDEX IF NOT EXISTS idx_listings_seller ON nft_listings(seller_id);
CREATE INDEX IF NOT EXISTS idx_listings_status ON nft_listings(status);
CREATE INDEX IF NOT EXISTS idx_listings_nft_id ON nft_listings(nft_id);

-- ============================================
-- ТАБЛИЦА 3: Настройки системы (system_settings)
-- ============================================
CREATE TABLE IF NOT EXISTS system_settings (
    id SERIAL PRIMARY KEY,
    setting_key TEXT UNIQUE NOT NULL,
    setting_value TEXT NOT NULL,
    updated_at TIMESTAMP DEFAULT NOW() NOT NULL,
    updated_by BIGINT REFERENCES users(id) ON DELETE SET NULL
);

-- Индекс для system_settings
CREATE INDEX IF NOT EXISTS idx_settings_key ON system_settings(setting_key);

-- Вставка начальных настроек
INSERT INTO system_settings (setting_key, setting_value) VALUES
    ('support_username', 'your_support_username'),
    ('card_number', '0000 0000 0000 0000'),
    ('card_holder', 'CARDHOLDER NAME'),
    ('card_bank', 'Bank Name')
ON CONFLICT (setting_key) DO NOTHING;

-- ============================================
-- ТАБЛИЦА 4: Админы (admins)
-- ============================================
CREATE TABLE IF NOT EXISTS admins (
    user_id BIGINT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    is_active BOOLEAN DEFAULT TRUE NOT NULL,
    created_at TIMESTAMP DEFAULT NOW() NOT NULL
);

-- ============================================
-- ТАБЛИЦА 5: История транзакций (transactions)
-- ============================================
CREATE TABLE IF NOT EXISTS transactions (
    id SERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    type TEXT NOT NULL CHECK (type IN ('deposit', 'withdraw', 'buy', 'sell', 'gift')),
    title TEXT NOT NULL,
    amount DECIMAL(10, 2) NOT NULL,
    nft_id TEXT,
    nft_title TEXT,
    created_at TIMESTAMP DEFAULT NOW() NOT NULL
);

-- Индексы для transactions
CREATE INDEX IF NOT EXISTS idx_transactions_user ON transactions(user_id);
CREATE INDEX IF NOT EXISTS idx_transactions_type ON transactions(type);
CREATE INDEX IF NOT EXISTS idx_transactions_created ON transactions(created_at DESC);

-- ============================================
-- ТАБЛИЦА 6: NFT пользователей (user_nfts)
-- ============================================
CREATE TABLE IF NOT EXISTS user_nfts (
    id SERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    nft_id TEXT NOT NULL,
    nft_title TEXT NOT NULL,
    nft_subtitle TEXT,
    nft_description TEXT,
    nft_image TEXT NOT NULL,
    nft_price DECIMAL(10, 2) NOT NULL,
    nft_collection TEXT,
    nft_model TEXT,
    nft_backdrop TEXT,
    origin TEXT DEFAULT 'purchase' CHECK (origin IN ('gift', 'purchase')),
    purchased_at TIMESTAMP DEFAULT NOW() NOT NULL,
    UNIQUE(user_id, nft_id)
);

-- Индексы для user_nfts
CREATE INDEX IF NOT EXISTS idx_user_nfts_user ON user_nfts(user_id);
CREATE INDEX IF NOT EXISTS idx_user_nfts_nft_id ON user_nfts(nft_id);
CREATE INDEX IF NOT EXISTS idx_user_nfts_origin ON user_nfts(origin);

-- ============================================
-- ТАБЛИЦА 7: Заявки на пополнение (deposit_requests)
-- ============================================
CREATE TABLE IF NOT EXISTS deposit_requests (
    id SERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    amount DECIMAL(10, 2) NOT NULL,
    amount_rub DECIMAL(10, 2) NOT NULL,
    status TEXT DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'rejected')),
    created_at TIMESTAMP DEFAULT NOW() NOT NULL,
    processed_at TIMESTAMP,
    processed_by BIGINT REFERENCES users(id) ON DELETE SET NULL
);

-- Индексы для deposit_requests
CREATE INDEX IF NOT EXISTS idx_deposit_requests_user ON deposit_requests(user_id);
CREATE INDEX IF NOT EXISTS idx_deposit_requests_status ON deposit_requests(status);
CREATE INDEX IF NOT EXISTS idx_deposit_requests_created ON deposit_requests(created_at DESC);

-- ============================================
-- ФУНКЦИЯ: Автоматическое обновление updated_at
-- ============================================
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

-- ============================================
-- ТРИГГЕРЫ: Для автоматического обновления updated_at
-- ============================================

-- Триггер для users
DROP TRIGGER IF EXISTS update_users_updated_at ON users;
CREATE TRIGGER update_users_updated_at 
BEFORE UPDATE ON users
FOR EACH ROW 
EXECUTE FUNCTION update_updated_at_column();

-- Триггер для nft_listings
DROP TRIGGER IF EXISTS update_listings_updated_at ON nft_listings;
CREATE TRIGGER update_listings_updated_at 
BEFORE UPDATE ON nft_listings
FOR EACH ROW 
EXECUTE FUNCTION update_updated_at_column();

-- Триггер для system_settings
DROP TRIGGER IF EXISTS update_settings_updated_at ON system_settings;
CREATE TRIGGER update_settings_updated_at 
BEFORE UPDATE ON system_settings
FOR EACH ROW 
EXECUTE FUNCTION update_updated_at_column();

-- ============================================
-- REALTIME: Включение для синхронизации
-- ============================================

-- Включаем Realtime для всех таблиц
DO $$ 
BEGIN
    -- users
    BEGIN
        ALTER PUBLICATION supabase_realtime ADD TABLE users;
    EXCEPTION
        WHEN duplicate_object THEN NULL;
    END;
    
    -- nft_listings
    BEGIN
        ALTER PUBLICATION supabase_realtime ADD TABLE nft_listings;
    EXCEPTION
        WHEN duplicate_object THEN NULL;
    END;
    
    -- transactions
    BEGIN
        ALTER PUBLICATION supabase_realtime ADD TABLE transactions;
    EXCEPTION
        WHEN duplicate_object THEN NULL;
    END;
    
    -- user_nfts
    BEGIN
        ALTER PUBLICATION supabase_realtime ADD TABLE user_nfts;
    EXCEPTION
        WHEN duplicate_object THEN NULL;
    END;
    
    -- deposit_requests
    BEGIN
        ALTER PUBLICATION supabase_realtime ADD TABLE deposit_requests;
    EXCEPTION
        WHEN duplicate_object THEN NULL;
    END;
END $$;

-- ============================================
-- ПРОВЕРКА: Вывод количества записей в таблицах
-- ============================================
SELECT 'users' as table_name, COUNT(*) as row_count FROM users
UNION ALL
SELECT 'nft_listings', COUNT(*) FROM nft_listings
UNION ALL
SELECT 'system_settings', COUNT(*) FROM system_settings
UNION ALL
SELECT 'admins', COUNT(*) FROM admins
UNION ALL
SELECT 'transactions', COUNT(*) FROM transactions
UNION ALL
SELECT 'user_nfts', COUNT(*) FROM user_nfts
UNION ALL
SELECT 'deposit_requests', COUNT(*) FROM deposit_requests
ORDER BY table_name;

-- ============================================
-- ГОТОВО! 🎉
-- ============================================
-- 
-- Все таблицы созданы и настроены!
-- 
-- Теперь вы можете:
-- 1. Запустить бота: python bot.py
-- 2. Запустить сайт: npm run dev (в папке portal-market)
-- 3. Использовать /admin для настройки карты и поддержки
-- 4. Использовать /worker для управления заявками
-- 
-- ============================================
-- ПОЛЕЗНЫЕ ЗАПРОСЫ
-- ============================================

-- Посмотреть всех пользователей:
-- SELECT id, username, first_name, balance, created_at FROM users ORDER BY created_at DESC;

-- Посмотреть все листинги:
-- SELECT l.id, l.nft_title, l.price, l.status, u.username as seller 
-- FROM nft_listings l 
-- JOIN users u ON l.seller_id = u.id 
-- ORDER BY l.created_at DESC;

-- Посмотреть все транзакции:
-- SELECT t.*, u.username 
-- FROM transactions t 
-- JOIN users u ON t.user_id = u.id 
-- ORDER BY t.created_at DESC 
-- LIMIT 20;

-- Посмотреть NFT пользователя:
-- SELECT * FROM user_nfts WHERE user_id = YOUR_TELEGRAM_ID;

-- Посмотреть заявки на пополнение:
-- SELECT d.*, u.username 
-- FROM deposit_requests d 
-- JOIN users u ON d.user_id = u.id 
-- WHERE d.status = 'pending'
-- ORDER BY d.created_at DESC;

-- Обновить баланс пользователя:
-- UPDATE users SET balance = 1000 WHERE id = YOUR_TELEGRAM_ID;

-- Сделать пользователя админом:
-- INSERT INTO admins (user_id, is_active) VALUES (YOUR_TELEGRAM_ID, true)
-- ON CONFLICT (user_id) DO UPDATE SET is_active = true;

-- Посмотреть рефералов пользователя:
-- SELECT id, username, first_name, balance, created_at 
-- FROM users 
-- WHERE referrer_id = YOUR_TELEGRAM_ID
-- ORDER BY created_at DESC;

-- ============================================
-- БЕЗОПАСНОСТЬ (Row Level Security) - ОПЦИОНАЛЬНО
-- ============================================
-- 
-- Для продакшена рекомендуется настроить RLS:
-- 
-- Включить RLS:
-- ALTER TABLE users ENABLE ROW LEVEL SECURITY;
-- ALTER TABLE nft_listings ENABLE ROW LEVEL SECURITY;
-- ALTER TABLE transactions ENABLE ROW LEVEL SECURITY;
-- ALTER TABLE user_nfts ENABLE ROW LEVEL SECURITY;
-- ALTER TABLE deposit_requests ENABLE ROW LEVEL SECURITY;
-- 
-- Примеры политик:
-- 
-- CREATE POLICY "Users can view own data" ON users
-- FOR SELECT USING (auth.uid()::bigint = id);
-- 
-- CREATE POLICY "Users can view own NFTs" ON user_nfts
-- FOR SELECT USING (auth.uid()::bigint = user_id);
-- 
-- CREATE POLICY "Users can view own transactions" ON transactions
-- FOR SELECT USING (auth.uid()::bigint = user_id);
-- 
-- CREATE POLICY "Admins can manage everything" ON system_settings
-- FOR ALL USING (
--   EXISTS (SELECT 1 FROM admins WHERE user_id = auth.uid()::bigint AND is_active = true)
-- );
-- 
-- ============================================
