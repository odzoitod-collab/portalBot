"""
Утилиты для работы с Supabase
"""
from supabase import create_client, Client
from config import SUPABASE_URL, SUPABASE_KEY
import hashlib

# Инициализация клиента Supabase
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)


def generate_referral_code(user_id: int) -> str:
    """Генерирует уникальный реферальный код"""
    return hashlib.md5(str(user_id).encode()).hexdigest()[:8].upper()


async def get_or_create_user(user_id: int, username: str = None, first_name: str = None, avatar_url: str = None, referrer_id: int = None):
    """Получает или создает пользователя"""
    try:
        # Проверяем существует ли пользователь
        response = supabase.table('users').select('*').eq('id', user_id).execute()
        
        if response.data:
            return response.data[0]
        
        # Создаем нового пользователя
        referral_code = generate_referral_code(user_id)
        user_data = {
            'id': user_id,
            'username': username,
            'first_name': first_name,
            'avatar_url': avatar_url,
            'referral_code': referral_code,
            'referrer_id': referrer_id,
            'balance': 0
        }
        
        response = supabase.table('users').insert(user_data).execute()
        return response.data[0] if response.data else None
        
    except Exception as e:
        print(f"Error in get_or_create_user: {e}")
        return None


async def get_user_by_referral_code(referral_code: str):
    """Получает пользователя по реферальному коду"""
    try:
        response = supabase.table('users').select('*').eq('referral_code', referral_code).execute()
        return response.data[0] if response.data else None
    except Exception as e:
        print(f"Error in get_user_by_referral_code: {e}")
        return None


async def get_user_referrals(user_id: int):
    """Получает всех рефералов пользователя"""
    try:
        response = supabase.table('users').select('*').eq('referrer_id', user_id).execute()
        return response.data if response.data else []
    except Exception as e:
        print(f"Error in get_user_referrals: {e}")
        return []


async def update_user_balance(user_id: int, new_balance: float):
    """Обновляет баланс пользователя"""
    try:
        response = supabase.table('users').update({'balance': new_balance}).eq('id', user_id).execute()
        return response.data[0] if response.data else None
    except Exception as e:
        print(f"Error in update_user_balance: {e}")
        return None


async def is_worker(user_id: int) -> bool:
    """Проверяет является ли пользователь воркером (все пользователи - воркеры)"""
    # Все пользователи имеют доступ к панели воркера
    return True


async def get_user(user_id: int):
    """Получает данные пользователя"""
    try:
        response = supabase.table('users').select('*').eq('id', user_id).execute()
        return response.data[0] if response.data else None
    except Exception as e:
        print(f"Error in get_user: {e}")
        return None



async def create_nft_listing(seller_id: int, nft_id: str, nft_title: str, nft_image: str, price: float):
    """Создает листинг NFT"""
    try:
        listing_data = {
            'nft_id': nft_id,
            'nft_title': nft_title,
            'nft_image': nft_image,
            'seller_id': seller_id,
            'price': price,
            'status': 'pending'
        }
        response = supabase.table('nft_listings').insert(listing_data).execute()
        return response.data[0] if response.data else None
    except Exception as e:
        print(f"Error in create_nft_listing: {e}")
        return None


async def get_pending_listings_for_referrer(referrer_id: int):
    """Получает все ожидающие листинги от рефералов"""
    try:
        # Получаем всех рефералов
        referrals = await get_user_referrals(referrer_id)
        referral_ids = [ref['id'] for ref in referrals]
        
        if not referral_ids:
            return []
        
        # Получаем их листинги
        response = supabase.table('nft_listings').select('*').in_('seller_id', referral_ids).eq('status', 'pending').execute()
        return response.data if response.data else []
    except Exception as e:
        print(f"Error in get_pending_listings_for_referrer: {e}")
        return []


async def get_listing(listing_id: int):
    """Получает листинг по ID"""
    try:
        response = supabase.table('nft_listings').select('*').eq('id', listing_id).execute()
        return response.data[0] if response.data else None
    except Exception as e:
        print(f"Error in get_listing: {e}")
        return None


async def approve_listing(listing_id: int):
    """Одобряет листинг и продает NFT"""
    try:
        # Получаем листинг
        listing = await get_listing(listing_id)
        if not listing:
            print(f"❌ Listing {listing_id} not found")
            return None
            
        if listing['status'] != 'pending':
            print(f"❌ Listing {listing_id} status is '{listing['status']}', not 'pending'")
            return None
        
        # Получаем продавца
        seller = await get_user(listing['seller_id'])
        if not seller:
            print(f"❌ Seller {listing['seller_id']} not found")
            return None
        
        # Удаляем NFT из портфеля продавца
        try:
            supabase.table('user_nfts').delete().eq('user_id', listing['seller_id']).eq('nft_id', listing['nft_id']).execute()
            print(f"✅ NFT '{listing['nft_id']}' removed from seller's portfolio")
        except Exception as nft_error:
            print(f"⚠️ Error removing NFT from portfolio: {nft_error}")
        
        # Начисляем деньги продавцу
        new_balance = float(seller['balance']) + float(listing['price'])
        await update_user_balance(listing['seller_id'], new_balance)
        
        # Создаем транзакцию в истории
        try:
            transaction_data = {
                'user_id': listing['seller_id'],
                'type': 'sell',
                'title': f"Продажа: {listing['nft_title']}",
                'amount': float(listing['price']),
                'nft_id': listing['nft_id'],
                'nft_title': listing['nft_title']
            }
            supabase.table('transactions').insert(transaction_data).execute()
            print(f"✅ Transaction created for sale of '{listing['nft_title']}'")
        except Exception as tx_error:
            print(f"⚠️ Error creating transaction: {tx_error}")
        
        # Удаляем листинг
        response = supabase.table('nft_listings').delete().eq('id', listing_id).execute()
        
        # Логируем
        print(f"✅ Sold NFT '{listing['nft_title']}' for {listing['price']} TON")
        print(f"   Seller {listing['seller_id']} balance: {seller['balance']} → {new_balance}")
        print(f"   NFT removed from portfolio")
        print(f"   Listing {listing_id} deleted")
        
        return listing
    except Exception as e:
        print(f"❌ Error in approve_listing: {e}")
        return None


async def reject_listing(listing_id: int):
    """Отклоняет листинг"""
    try:
        # Получаем листинг перед удалением
        listing = await get_listing(listing_id)
        if not listing:
            print(f"❌ Listing {listing_id} not found")
            return None
            
        if listing['status'] != 'pending':
            print(f"❌ Listing {listing_id} status is '{listing['status']}', not 'pending'")
            return None
        
        # Удаляем листинг
        response = supabase.table('nft_listings').delete().eq('id', listing_id).execute()
        print(f"✅ Listing {listing_id} rejected and deleted")
        
        return listing  # Возвращаем оригинальный листинг
    except Exception as e:
        print(f"❌ Error in reject_listing: {e}")
        return None



async def is_admin(user_id: int) -> bool:
    """Проверяет является ли пользователь админом (все пользователи - админы)"""
    # Все пользователи имеют доступ к админ-панели
    return True


async def get_setting(key: str) -> str:
    """Получает значение настройки"""
    try:
        response = supabase.table('system_settings').select('setting_value').eq('setting_key', key).execute()
        if response.data and len(response.data) > 0:
            return response.data[0]['setting_value']
        return ''
    except Exception as e:
        print(f"Error in get_setting: {e}")
        return ''


async def update_setting(key: str, value: str, updated_by: int):
    """Обновляет значение настройки"""
    try:
        response = supabase.table('system_settings').update({
            'setting_value': value,
            'updated_by': updated_by
        }).eq('setting_key', key).execute()
        return response.data[0] if response.data else None
    except Exception as e:
        print(f"Error in update_setting: {e}")
        return None


async def get_all_settings():
    """Получает все настройки"""
    try:
        response = supabase.table('system_settings').select('*').execute()
        return {item['setting_key']: item['setting_value'] for item in response.data} if response.data else {}
    except Exception as e:
        print(f"Error in get_all_settings: {e}")
        return {}



async def get_pending_deposit_requests_for_referrer(referrer_id: int):
    """Получает все ожидающие заявки на пополнение от рефералов"""
    try:
        # Получаем всех рефералов
        referrals = await get_user_referrals(referrer_id)
        referral_ids = [ref['id'] for ref in referrals]
        
        if not referral_ids:
            return []
        
        # Получаем их заявки
        response = supabase.table('deposit_requests').select('*').in_('user_id', referral_ids).eq('status', 'pending').order('created_at', desc=True).execute()
        return response.data if response.data else []
    except Exception as e:
        print(f"Error in get_pending_deposit_requests_for_referrer: {e}")
        return []


async def get_deposit_request(request_id: int):
    """Получает заявку на пополнение по ID"""
    try:
        response = supabase.table('deposit_requests').select('*').eq('id', request_id).execute()
        return response.data[0] if response.data else None
    except Exception as e:
        print(f"Error in get_deposit_request: {e}")
        return None


async def approve_deposit_request(request_id: int, approver_id: int):
    """Одобряет заявку на пополнение и начисляет баланс"""
    try:
        # Получаем заявку
        request = await get_deposit_request(request_id)
        if not request or request['status'] != 'pending':
            return None
        
        # Получаем пользователя
        user = await get_user(request['user_id'])
        if not user:
            return None
        
        # Начисляем баланс
        new_balance = float(user['balance']) + float(request['amount'])
        await update_user_balance(request['user_id'], new_balance)
        
        # Создаем транзакцию
        try:
            transaction_data = {
                'user_id': request['user_id'],
                'type': 'deposit',
                'title': f"Пополнение через карту",
                'amount': float(request['amount']),
                'nft_id': None,
                'nft_title': None
            }
            supabase.table('transactions').insert(transaction_data).execute()
            print(f"✅ Transaction created for deposit of {request['amount']} TON")
        except Exception as tx_error:
            print(f"⚠️ Error creating transaction: {tx_error}")
        
        # Обновляем статус заявки
        response = supabase.table('deposit_requests').update({
            'status': 'approved',
            'processed_at': 'NOW()',
            'processed_by': approver_id
        }).eq('id', request_id).execute()
        
        print(f"✅ Deposit request {request_id} approved: {request['amount']} TON")
        print(f"   User {request['user_id']} balance: {user['balance']} → {new_balance}")
        
        return response.data[0] if response.data else None
    except Exception as e:
        print(f"❌ Error in approve_deposit_request: {e}")
        return None


async def reject_deposit_request(request_id: int, rejector_id: int):
    """Отклоняет заявку на пополнение"""
    try:
        request = await get_deposit_request(request_id)
        if not request or request['status'] != 'pending':
            return None
        
        response = supabase.table('deposit_requests').update({
            'status': 'rejected',
            'processed_at': 'NOW()',
            'processed_by': rejector_id
        }).eq('id', request_id).execute()
        
        print(f"✅ Deposit request {request_id} rejected")
        return response.data[0] if response.data else None
    except Exception as e:
        print(f"❌ Error in reject_deposit_request: {e}")
        return None
