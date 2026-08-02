import asyncio
import os
import json
from aiohttp import web
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, LabeledPrice, BotCommand
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from dotenv import load_dotenv
from google import genai

# ==========================================
# 1. إعداد المفاتيح والحالات
# ==========================================
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
ADMIN_ID = int(os.getenv("ADMIN_ID", 8280243933)) 

client = genai.Client(api_key=GEMINI_API_KEY)

session = AiohttpSession(timeout=30)
bot = Bot(token=TELEGRAM_TOKEN, session=session)
dp = Dispatcher()

class PromoState(StatesGroup):
    waiting_for_code = State()

# ==========================================
# 📁 نظام حفظ الأكواد الدائم (promos.json)
# ==========================================
PROMOS_FILE = "promos.json"

def load_promo_codes():
    if os.path.exists(PROMOS_FILE):
        try:
            with open(PROMOS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    # أكواد افتراضية في حال عدم وجود الملف
    default_promos = {"1400": 50, "MISTX": 50}
    save_promo_codes(default_promos)
    return default_promos

def save_promo_codes(data):
    try:
        with open(PROMOS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Error saving promos: {e}")

promo_codes = load_promo_codes()
user_requests = {}
user_active_promo = {}
vip_users = set()

SUPPORT_URL = "https://t.me/DARKMAIL_77"
SUPPORT_KEYBOARD = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="💬 التواصل مع الدعم الفني", url=SUPPORT_URL)]
])

# ==========================================
# 🌐 خادم المنفذ الوهمي لـ Render (Port Timeout)
# ==========================================
async def dummy_health_check(request):
    return web.Response(text="MISTX Bot is running successfully!")

async def start_dummy_server():
    app = web.Application()
    app.router.add_get('/', dummy_health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f"🌐 Dummy HTTP Server running on port {port}")

# ==========================================
# 2. إعداد قائمة الأوامر الرسمية (زر ≡)
# ==========================================
async def setup_bot_commands():
    commands = [
        BotCommand(command="start", description="بدء استخدام المتجر 🚀"),
        BotCommand(command="code", description="إدخال كود الخصم 🎟️"),
        BotCommand(command="help", description="التواصل مع الدعم الفني 💬")
    ]
    await bot.set_my_commands(commands)

# ==========================================
# 3. لوحة تحكم المدير
# ==========================================
@dp.message(Command("admin"))
async def admin_panel(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    text = (
        "👑 **لوحة تحكم المدير (متجر MISTX):**\n\n"
        "➕ لإنشاء كود خصم:\n`/add_promo 1400 50`\n\n"
        "➖ لحذف كود خصم:\n`/del_promo 1400`\n\n"
        "📋 لعرض الأكواد الفعالة:\n`/promos`\n\n"
        "🌟 إضافة وصول مجاني دائم (VIP):\n`/free 123456789`\n\n"
        "🗑 إزالة وصول مجاني:\n`/remove 123456789`"
    )
    await message.answer(text, parse_mode="Markdown")

@dp.message(Command("add_promo"))
async def add_promo_code(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    try:
        parts = message.text.split()
        code = parts[1].strip().upper()
        discount = int(parts[2])
        promo_codes[code] = discount
        save_promo_codes(promo_codes)
        await message.answer(f"✅ تم إنشاء كود الخصم `{code}` بنسبة {discount}% وحفظه بنجاح.", parse_mode="Markdown")
    except:
        await message.answer("⚠️ الطريقة الصحيحة: `/add_promo CODE 50`", parse_mode="Markdown")

@dp.message(Command("del_promo"))
async def del_promo_code(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    try:
        code = message.text.split()[1].strip().upper()
        if code in promo_codes:
            del promo_codes[code]
            save_promo_codes(promo_codes)
            await message.answer(f"✅ تم حذف الكود `{code}` بنجاح.", parse_mode="Markdown")
        else:
            await message.answer("⚠️ هذا الكود غير موجود مسبقاً.")
    except:
        await message.answer("⚠️ الطريقة الصحيحة: `/del_promo CODE`", parse_mode="Markdown")

@dp.message(Command("promos"))
async def list_promos(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    if not promo_codes:
        await message.answer("لا توجد أكواد خصم فعالة حالياً.")
        return
    text = "🎟 **أكواد الخصم الفعالة حالياً:**\n\n"
    for code, discount in promo_codes.items():
        text += f"🔹 الكود: `{code}` (يخصم {discount}%)\n"
    await message.answer(text, parse_mode="Markdown")

@dp.message(Command("free"))
async def add_free_user(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    try:
        user_id = int(message.text.split()[1])
        vip_users.add(user_id)
        await message.answer(f"✅ تم إضافة العميل `{user_id}` للقائمة المجانية الدائمة (VIP).", parse_mode="Markdown")
    except:
        pass

@dp.message(Command("remove"))
async def remove_vip_user(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    try:
        user_id = int(message.text.split()[1])
        vip_users.discard(user_id)
        await message.answer(f"✅ تم إزالة العميل `{user_id}` من قائمة VIP.", parse_mode="Markdown")
    except:
        pass

# ==========================================
# 4. معالجة الأوامر وكود الخصم
# ==========================================
@dp.message(CommandStart())
async def command_start_handler(message: types.Message, state: FSMContext):
    await state.clear()
    user_id = message.from_user.id
    safe_name = message.from_user.full_name.replace("_", " ").replace("*", "").replace("`", "")
    
    welcome_text = (
        f"أهلاً بك {safe_name} في متجر MISTX الرقمي للبرمجة! 🚀\n\n"
        "أنا مساعدك الذكي ومطور الأكواد. اطلب أي سكربت برمجي أو أداة وسأقوم بتجهيزها لك فوراً."
    )
    
    await message.answer(welcome_text, parse_mode="Markdown")
    
    if user_id != ADMIN_ID:
        try:
            await bot.send_message(ADMIN_ID, f"🔔 شخص جديد دخل المتجر!\nالاسم: {safe_name}\nالـ ID: `{user_id}`", parse_mode="Markdown")
        except:
            pass

@dp.message(Command("help"))
async def command_help_handler(message: types.Message):
    help_text = "🛠 **قسم الدعم الفني:**\nلأي استفسار أو مشكلة، يمكنك التواصل المباشر مع الإدارة عبر الزر أدناه:"
    await message.answer(help_text, reply_markup=SUPPORT_KEYBOARD, parse_mode="Markdown")

@dp.message(Command("code"))
async def apply_promo_command(message: types.Message, state: FSMContext):
    args = message.text.split()
    if len(args) > 1:
        await validate_and_apply_promo(args[1], message)
        await state.clear()
    else:
        await state.set_state(PromoState.waiting_for_code)
        await message.answer("✏️ **يرجى إرسال كود الخصم الآن في الرسالة القادمة:**", parse_mode="Markdown")

@dp.message(PromoState.waiting_for_code)
async def process_promo_input(message: types.Message, state: FSMContext):
    if message.text and message.text.startswith("/"):
        await state.clear()
        return
    await validate_and_apply_promo(message.text, message)
    await state.clear()

async def validate_and_apply_promo(input_code: str, message: types.Message):
    user_id = message.from_user.id
    cleaned_code = input_code.strip().upper()
    
    if cleaned_code in promo_codes:
        discount = promo_codes[cleaned_code]
        user_active_promo[user_id] = discount
        if discount == 100:
            await message.answer("🎁 **تم تفعيل كود الخصم بنسبة 100%! طلبك القادم مجاني بالكامل.**")
        else:
            await message.answer(f"🎉 **تم تفعيل كود الخصم ({discount}%) بنجاح!**\nاكتب طلبك البرمجي الآن وسيتم تطبيق الخصم.")
    else:
        await message.answer("❌ كود الخصم غير صحيح أو ربما انتهت صلاحيته.")

# ==========================================
# 5. توليد الكود والذكاء الاصطناعي
# ==========================================
async def generate_and_send_code(prompt_text, message: types.Message):
    await message.answer("⏳ جاري توليد وكتابة السكربت البرمجي عبر الذكاء الاصطناعي الآن...")
    try:
        coding_prompt = (
            "أنت مبرمج خبير ومحترف. قم بكتابة الكود البرمجي الكامل والنظيف المطلوب بناءً على طلب العميل:\n"
            f"طلب العميل: {prompt_text}\n"
            "اكتب الكود بلغة بايثون واضحة مع تعليقات تشرح كيفية الاستخدام."
        )
        response = client.models.generate_content(
            model='gemini-3.5-flash',
            contents=coding_prompt,
        )
        await message.answer(
            f"🚀 **إليك السكربت الخاص بك جاهزاً:**\n\n{response.text}\n\n"
            "شكراً لتعاملك مع متجر MISTX! إذا أردت أي تعديل، أخبرني بذلك."
        )
    except Exception as e:
        print(f"Error generating code: {e}")
        await message.answer(
            "⚠️ **حدث خطأ غير متوقع أثناء توليد الكود.**\nيرجى التواصل مباشرة مع الدعم الفني لمساعدتك:",
            reply_markup=SUPPORT_KEYBOARD,
            parse_mode="Markdown"
        )

@dp.message()
async def handle_chat_or_order(message: types.Message):
    user_text = message.text
    user_id = message.from_user.id
    await bot.send_chat_action(chat_id=message.chat.id, action="typing")
    
    try:
        analysis_prompt = (
            "حلل الرسالة التالية. هل يطلب العميل صراحة كتابة كود برمجي أو أداة؟ "
            f"رسالة العميل: '{user_text}'\n"
            "رد بـ كلمة واحدة فقط 'YES' أو 'NO'."
        )
        check_res = client.models.generate_content(model='gemini-3.5-flash', contents=analysis_prompt)
        is_coding_request = "YES" in check_res.text.upper()
        
        if not is_coding_request:
            chat_prompt = f"أنت مستشار لمتجر MISTX. العميل يقول: {user_text}. أجب بلباقة واقترح المساعدة برمجياً."
            chat_response = client.models.generate_content(model='gemini-3.5-flash', contents=chat_prompt)
            await message.answer(chat_response.text)
            return

        discount = user_active_promo.get(user_id, 0)
        
        if user_id in vip_users or user_id == ADMIN_ID or discount == 100:
            if discount == 100:
                await message.answer("🎁 **تم تطبيق خصم 100%! طلبك مجاني بالكامل.**")
                user_active_promo.pop(user_id, None) 
            elif user_id != ADMIN_ID:
                await message.answer("🎁 **لديك اشتراك مجاني دائم (VIP)!** لا حاجة للدفع.")
            
            await generate_and_send_code(user_text, message)
            return

        pricing_prompt = (
            f"حلل طلب العميل: {user_text}. حدد السعر بالدولار. وقت الإنجاز 'تسليم فوري'."
            'رد بصيغة JSON حصرية فقط: {"price_usd": 7, "details": "وصف", "time": "تسليم فوري"}'
        )
        response = client.models.generate_content(model='gemini-3.5-flash', contents=pricing_prompt)
        clean_response = response.text.strip().replace("```json", "").replace("```", "")
        data = json.loads(clean_response)
        
        price_usd = int(data.get("price_usd", 7))
        price_stars = price_usd * 15
        
        if discount > 0:
            price_usd = max(1, int(price_usd - (price_usd * discount / 100)))
            price_stars = max(15, int(price_stars - (price_stars * discount / 100)))
            discount_text = f"🎉 **تم تطبيق كود الخصم ({discount}%)!**\n"
        else:
            discount_text = ""
        
        details = data.get("details", "كود برمجي مخصص")
        
        user_requests[user_id] = {
            "prompt": user_text,
            "details": details,
            "price_usd": price_usd,
            "price_stars": price_stars
        }
        
        paypal_dynamic_link = f"https://paypal.me/DarkMail641/{price_usd}USD"
        paypal_support_link = "https://www.paypal.com/ncp/payment/2JSPL52BVSGDY"
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"💳 دفع عبر PayPal ({price_usd}$)", url=paypal_dynamic_link)],
            [InlineKeyboardButton(text=f"⭐ دفع عبر نجوم تلجرام ({price_stars} نجمة)", callback_data=f"buy_stars_{price_stars}")],
            [InlineKeyboardButton(text="💬 التواصل مع الدعم الفني", url=SUPPORT_URL)]
        ])
        
        text_msg = (
            f"✅ **تم دراسة طلبك البرمجي!**\n\n"
            f"{discount_text}"
            f"📌 **التفاصيل:** {details}\n"
            f"💰 **التكلفة المطلوبة:** {price_usd} دولار (أو {price_stars} نجمة)\n\n"
            f"اختر وسيلة الدفع المناسبة بالأسفل لاستلام الكود فوراً:"
        )
        
        await message.answer(text_msg, reply_markup=keyboard, parse_mode="Markdown")
        
    except Exception as e:
        print(f"Error processing order: {e}")
        await message.answer(
            "⚠️ **تعذر معالجة الطلب حالياً.**\nإذا واجهتك أي مشكلة، تواصل مباشرة مع الدعم الفني:",
            reply_markup=SUPPORT_KEYBOARD,
            parse_mode="Markdown"
        )

# ==========================================
# 6. معالجة الدفع بالنجوم
# ==========================================
@dp.callback_query(F.data.startswith("buy_stars_"))
async def process_stars_buy(callback_query: types.CallbackQuery):
    await callback_query.answer()
    user_id = callback_query.from_user.id
    user_data = user_requests.get(user_id)
    
    if not user_data:
        await bot.send_message(
            user_id, 
            "⚠️ انتهت صلاحية الجلسة. أعد كتابة الطلب أو تواصل مع الدعم الفني:",
            reply_markup=SUPPORT_KEYBOARD
        )
        return

    await bot.send_invoice(
        chat_id=user_id,
        title="طلب كود برمجي مخصص (MISTX)",
        description=user_data["details"][:250],
        payload=f"code_stars_{user_id}",
        provider_token="",
        currency="XTR",
        prices=[LabeledPrice(label="السكربت البرمجي", amount=user_data["price_stars"])]
    )

@dp.pre_checkout_query()
async def process_pre_checkout(pre_checkout_query: types.PreCheckoutQuery):
    await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)

@dp.message(F.content_type == types.ContentType.SUCCESSFUL_PAYMENT)
async def process_successful_payment(message: types.Message):
    user_id = message.from_user.id
    user_data = user_requests.get(user_id)
    user_active_promo.pop(user_id, None)

    safe_name = message.from_user.full_name.replace("_", " ").replace("*", "").replace("`", "")
    admin_notification = (
        f"💸 **عملية شراء جديدة تمت!**\n\n"
        f"👤 العميل: {safe_name}\n"
        f"🆔 الآيدي: `{user_id}`\n"
        f"💰 المبلغ: {message.successful_payment.total_amount} نجمة\n"
        f"📦 الطلب: {user_data['prompt'][:100] if user_data else 'طلب مخصص'}..."
    )
    try:
        await bot.send_message(ADMIN_ID, admin_notification, parse_mode="Markdown")
    except:
        pass

    await message.answer("🎉 **تم استلام الدفع بنجاح!**")
    prompt_text = user_data['prompt'] if user_data else 'كود برمجي'
    await generate_and_send_code(prompt_text, message)

# ==========================================
# 7. التشغيل الرئيسي
# ==========================================
async def main():
    await start_dummy_server()
    await setup_bot_commands()
    print("🚀 متجر MISTX يعمل الآن مع الحفظ الدائم للأكواد!")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
