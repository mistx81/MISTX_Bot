import os
import json
import asyncio
import logging
import traceback
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, LabeledPrice, PreCheckoutQuery

from google import genai
from google.genai import types as genai_types

# ==========================================
# 1. سيرفر HTTP وهمي لإرضاء Render ومنع إغلاق الخدمة
# ==========================================
class DummyHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html; charset=utf-8')
        self.end_headers()
        self.wfile.write("MISTX Bot is running successfully!".encode('utf-8'))

    def log_message(self, format, *args):
        return

def run_dummy_server():
    port = int(os.getenv("PORT", 10000))
    server = HTTPServer(('0.0.0.0', port), DummyHandler)
    print(f"==> Dummy HTTP Server running on port {port}")
    server.serve_forever()

threading.Thread(target=run_dummy_server, daemon=True).start()

# ==========================================
# 2. إعداد المتغيرات الأساسية والعملاء
# ==========================================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
ADMIN_ID = int(os.getenv("ADMIN_ID", "7088991709"))
SUPPORT_URL = os.getenv("SUPPORT_URL", "https://t.me/MISTX_Support")

logging.basicConfig(level=logging.INFO)

if not TELEGRAM_TOKEN or not GEMINI_API_KEY:
    raise ValueError("⚠️ الرجاء التأكد من ضبط TELEGRAM_TOKEN و GEMINI_API_KEY في متغيرات البيئة بـ Render!")

bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher()
client = genai.Client(api_key=GEMINI_API_KEY)

MODEL_NAME = 'gemini-2.5-flash'

# قواعد البيانات المؤقتة في الذاكرة
promo_codes = {
    "MISTX100": 100,
    "MISTX50": 50,
    "MISTX20": 20,
    "NEW": 50
}
user_active_promo = {}  # {user_id: discount_percentage}
vip_users = set()        # قائمة الـ VIP
user_requests = {}      # حفظ الطلبات المعلقة {user_id: details}

# قاعدة بيانات المستخدمين الفريدين (تحسب كل شخص مرة واحدة فقط)
bot_users = {}  # {user_id: {"name": str, "username": str}}

SUPPORT_KEYBOARD = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="💬 التواصل مع الدعم الفني", url=SUPPORT_URL)]
])

# ==========================================
# 3. الدوال المساعدة وتكشيف المستخدمين
# ==========================================

def register_user(user: types.User):
    """حفظ وتحديث بيانات المستخدم الفريد (يحسب مرة واحدة فقط)"""
    if user.id not in bot_users:
        bot_users[user.id] = {
            "name": user.first_name or "بدون اسم",
            "username": f"@{user.username}" if user.username else "بدون معرف"
        }

async def validate_and_apply_promo(code: str, message: types.Message):
    user_id = message.from_user.id
    discount = promo_codes.get(code)
    if discount is not None:
        user_active_promo[user_id] = discount
        await message.answer(
            f"🎉 <b>تم تفعيل كود الخصم ({discount}%) بنجاح!</b>\nاكتب طلبك البرمجي الآن وسيتم تطبيق الخصم تلقائياً.",
            parse_mode="HTML"
        )
    else:
        await message.answer("❌ <b>كود الخصم غير صحيح أو منتهي الصلاحية.</b>", parse_mode="HTML")

async def generate_and_send_code(user_prompt: str, message: types.Message):
    """توليد الكود البرمجي وإرساله للعميل مباشرة"""
    await bot.send_chat_action(chat_id=message.chat.id, action="typing")
    await message.answer("⏳ <b>جاري كتابة وتوليد الكود البرمجي الخاص بك، يرجى الانتظار...</b>", parse_mode="HTML")
    
    system_instruction = (
        "أنت مهندس برمجيات خبير في متجر MISTX. قم بكتابة كود برمجي ممتاز، نظيف، "
        "وموثق بالكامل بناءً على طلب العميل، وأضف شرحاً مختصراً لكيفية التشغيل."
    )
    
    try:
        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=user_prompt,
            config=genai_types.GenerateContentConfig(
                system_instruction=system_instruction
            )
        )
        
        code_result = response.text if response and response.text else "لم يتم توليد كود."
        
        if len(code_result) > 4000:
            for chunk in [code_result[i:i+4000] for i in range(0, len(code_result), 4000)]:
                await message.answer(chunk)
        else:
            await message.answer(code_result)
            
        await message.answer("✅ <b>تم تسليم الكود بنجاح!</b> شكراً لاستخدامك خدمات MISTX.", parse_mode="HTML")
    except Exception as e:
        logging.error(f"Error generating code: {e}\n{traceback.format_exc()}")
        await message.answer(
            "⚠️ حدث خطأ أثناء توليد الكود. تواصل مع الدعم الفني للمساعدة.",
            reply_markup=SUPPORT_KEYBOARD
        )

# ==========================================
# 4. لوحة تحكم المدير والأوامر الإدارية
# ==========================================

@dp.message(Command("admin"))
async def admin_dashboard(message: types.Message):
    register_user(message.from_user)
    if message.from_user.id != ADMIN_ID:
        return

    total_users = len(bot_users)
    dashboard_text = (
        "👑 <b>لوحة تحكم المدير (متجر MISTX):</b>\n\n"
        f"📊 <b>عدد المستخدمين الفريدين:</b> <code>{total_users}</code> شخص\n"
        "👥 <b>لعرض قائمة الأشخاص:</b> /users\n\n"
        "➕ <b>لإنشاء كود خصم:</b>\n"
        "<code>/add_promo NEW 50</code>\n\n"
        "➖ <b>لحذف كود خصم:</b>\n"
        "<code>/del_promo NEW</code>\n\n"
        "📋 <b>لعرض الأكواد الفعالة:</b>\n"
        "/promos\n\n"
        "🌟 <b>إعطاء شخص وصول مجاني دائم (VIP):</b>\n"
        "<code>/free 123456789</code>\n\n"
        "🗑️ <b>لإزالة الوصول المجاني الدائم:</b>\n"
        "<code>/remove 123456789</code>"
    )
    await message.answer(dashboard_text, parse_mode="HTML")

@dp.message(Command("users"))
async def list_users_cmd(message: types.Message):
    register_user(message.from_user)
    if message.from_user.id != ADMIN_ID:
        return

    if not bot_users:
        await message.answer("👥 لم يدخل أي مستخدم للبوت حتى الآن.")
        return

    text = f"👥 <b>قائمة الأشخاص الذين دخلوا البوت (الإجمالي: {len(bot_users)}):</b>\n\n"
    for idx, (uid, info) in enumerate(bot_users.items(), start=1):
        text += f"{idx}. <b>{info['name']}</b> ({info['username']}) - ID: <code>{uid}</code>\n"
        if len(text) > 3800:
            await message.answer(text, parse_mode="HTML")
            text = ""

    if text:
        await message.answer(text, parse_mode="HTML")

@dp.message(Command("add_promo"))
async def add_promo_cmd(message: types.Message):
    register_user(message.from_user)
    if message.from_user.id != ADMIN_ID:
        return
    try:
        args = message.text.split()[1:]
        if len(args) < 2:
            await message.answer("⚠️ الاستخدام الصحيح: <code>/add_promo CODE DISCOUNT</code>", parse_mode="HTML")
            return
        code = args[0].upper()
        discount = int(args[1])
        promo_codes[code] = discount
        await message.answer(f"✅ <b>تم إنشاء كود الخصم {code} بنسبة {discount}% وحفظه بنجاح.</b>", parse_mode="HTML")
    except Exception as e:
        await message.answer(f"❌ خطأ في إضافة الكود: {e}")

@dp.message(Command("del_promo"))
async def del_promo_cmd(message: types.Message):
    register_user(message.from_user)
    if message.from_user.id != ADMIN_ID:
        return
    try:
        args = message.text.split()[1:]
        if not args:
            await message.answer("⚠️ الاستخدام الصحيح: <code>/del_promo CODE</code>", parse_mode="HTML")
            return
        code = args[0].upper()
        if code in promo_codes:
            del promo_codes[code]
            await message.answer(f"🗑️ <b>تم حذف كود الخصم {code} بنجاح.</b>", parse_mode="HTML")
        else:
            await message.answer("❌ كود الخصم غير موجود.")
    except Exception as e:
        await message.answer(f"❌ خطأ: {e}")

@dp.message(Command("free"))
async def add_vip_cmd(message: types.Message):
    register_user(message.from_user)
    if message.from_user.id != ADMIN_ID:
        return
    try:
        args = message.text.split()[1:]
        if not args:
            await message.answer("⚠️ الاستخدام الصحيح: <code>/free USER_ID</code>", parse_mode="HTML")
            return
        target_id = int(args[0])
        vip_users.add(target_id)
        await message.answer(f"🌟 <b>تم منح المستخدم ID: <code>{target_id}</code> وصول مجاني دائم (VIP).</b>", parse_mode="HTML")
    except Exception as e:
        await message.answer(f"❌ خطأ: {e}")

@dp.message(Command("remove"))
async def remove_vip_cmd(message: types.Message):
    register_user(message.from_user)
    if message.from_user.id != ADMIN_ID:
        return
    try:
        args = message.text.split()[1:]
        if not args:
            await message.answer("⚠️ الاستخدام الصحيح: <code>/remove USER_ID</code>", parse_mode="HTML")
            return
        target_id = int(args[0])
        vip_users.discard(target_id)
        await message.answer(f"🗑️ <b>تم إزالة الوصول المجاني عن المستخدم ID: <code>{target_id}</code>.</b>", parse_mode="HTML")
    except Exception as e:
        await message.answer(f"❌ خطأ: {e}")

@dp.message(Command("promos"))
async def list_promos(message: types.Message):
    register_user(message.from_user)
    if not promo_codes:
        await message.answer("لا توجد أكواد خصم متاحة حالياً.")
        return
    text = "🎁 <b>أكواد الخصم الفعالة حالياً:</b>\n\n"
    for code, discount in promo_codes.items():
        text += f"🔹 الكود: <code>{code}</code> (خصم {discount}%)\n"
    await message.answer(text, parse_mode="HTML")

@dp.message(Command("code"))
async def prompt_code(message: types.Message):
    register_user(message.from_user)
    await message.answer("🔑 <b>يرجى إرسال كود الخصم الآن في الرسالة القادمة:</b>", parse_mode="HTML")

# ==========================================
# 5. معالجة الطلبات البرمجية والدردشة
# ==========================================

@dp.message(CommandStart())
async def start_cmd(message: types.Message):
    register_user(message.from_user)
    welcome_text = (
        f"أهلاً بك <b>{message.from_user.first_name}</b> في بوت الذكاء الفوري للأكواد <b>MISTX</b>! 🚀\n\n"
        "أنا مساعدك البرمجي الذكي. يمكنك إرسال أي طلب برمجي، سكربت، أو أداة ترغب في إنشائها وسأقوم بـ:\n"
        "1️⃣ تحليل الطلب فوراً.\n"
        "2️⃣ تقديم السعر التلقائي وطرق الدفع (PayPal / نجوم تلجرام).\n"
        "3️⃣ تسليم الكود البرمجي مباشرة عند إتمام الدفع!\n\n"
        "💡 <i>إذا كان لديك كود خصم، أرسله هنا أو استخدم /code قبل إرسال طلبك.</i>"
    )
    await message.answer(welcome_text, parse_mode="HTML")

@dp.message(F.text)
async def handle_chat_or_order(message: types.Message, state: FSMContext):
    register_user(message.from_user)
    user_text = message.text
    if not user_text:
        return
        
    user_id = message.from_user.id
    cleaned_input = user_text.strip().upper()

    # فحص كود الخصم
    if cleaned_input in promo_codes:
        await validate_and_apply_promo(cleaned_input, message)
        await state.clear()
        return

    await bot.send_chat_action(chat_id=message.chat.id, action="typing")
    
    try:
        # 1. فحص نوع الرسالة عبر الذكاء الاصطناعي
        analysis_prompt = (
            "حلل الرسالة التالية. هل يطلب العميل صراحة كتابة كود برمجي أو أداة أو سكربت أو حل مشكلة برمجية؟ "
            f"رسالة العميل: '{user_text}'\n"
            "رد بـ كلمة واحدة فقط 'YES' أو 'NO'."
        )
        check_res = client.models.generate_content(model=MODEL_NAME, contents=analysis_prompt)
        is_coding_request = "YES" in check_res.text.upper()
        
        if not is_coding_request:
            chat_prompt = f"أنت مستشار وخدمة عملاء لمتجر MISTX البرمجي. العميل يقول: {user_text}. أجب بلباقة واشرح كيف يمكنك مساعدته برمجياً."
            chat_response = client.models.generate_content(model=MODEL_NAME, contents=chat_prompt)
            await message.answer(chat_response.text)
            return

        discount = user_active_promo.get(user_id, 0)
        
        # فحص حالات الطلب المجاني (VIP / Admin / خصم 100% أو أكثر)
        if user_id in vip_users or user_id == ADMIN_ID or discount >= 100:
            if discount >= 100:
                await message.answer(f"🎁 <b>تم تطبيق خصم ({discount}%)! طلبك مجاني بالكامل.</b>", parse_mode="HTML")
                user_active_promo.pop(user_id, None)
            elif user_id == ADMIN_ID:
                await message.answer("👑 <b>أهلاً بك يا مدير النظام! جاري تنفيذ طلبك مجاناً...</b>", parse_mode="HTML")
            else:
                await message.answer("🎁 <b>لديك اشتراك مجاني دائم (VIP)!</b>", parse_mode="HTML")
            
            await generate_and_send_code(user_text, message)
            return

        # 2. تحديد السعر تلقائياً
        pricing_prompt = (
            f"حلل طلب العميل البرمجي التالي: '{user_text}'. "
            "حدد السعر المناسب بالدولار الأمريكي بناءً على تعقيد الطلب (من 3 إلى 50 دولار).\n"
            "رد بصيغة JSON حصرية فقط بدون أي نصوص أو markdown حولها:\n"
            '{"price_usd": 7, "details": "وصف قصير للسكربت", "time": "تسليم فوري"}'
        )
        response = client.models.generate_content(model=MODEL_NAME, contents=pricing_prompt)
        
        raw_text = response.text.strip()
        if raw_text.startswith("```"):
            raw_text = raw_text.split("```")[1]
            if raw_text.startswith("json"):
                raw_text = raw_text[4:]
        raw_text = raw_text.strip()
        
        try:
            data = json.loads(raw_text)
        except Exception:
            data = {"price_usd": 7, "details": "سكربت برمجي مخصص", "time": "تسليم فوري"}

        price_usd = int(data.get("price_usd", 7))
        
        if discount > 0:
            discounted_price = price_usd - (price_usd * discount / 100)
            price_usd = max(1, int(discounted_price)) if discounted_price > 0 else 0

        if price_usd <= 0:
            await message.answer("🎉 <b>تم خصم التكلفة بالكامل! طلبك مجاني.</b>", parse_mode="HTML")
            user_active_promo.pop(user_id, None)
            await generate_and_send_code(user_text, message)
            return

        price_stars = max(15, price_usd * 15)
        details = str(data.get("details", "كود برمجي مخصص"))
        
        user_requests[user_id] = {
            "prompt": user_text,
            "details": details,
            "price_usd": price_usd,
            "price_stars": price_stars
        }
        
        paypal_dynamic_link = f"https://paypal.me/DarkMail641/{price_usd}USD"
        discount_text = f"🎉 <b>تم تطبيق كود الخصم ({discount}%)!</b>\n" if discount > 0 else ""
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"💳 دفع عبر PayPal ({price_usd}$)", url=paypal_dynamic_link)],
            [InlineKeyboardButton(text=f"⭐ دفع عبر نجوم تلجرام ({price_stars} نجمة)", callback_data=f"buy_stars_{price_stars}")],
            [InlineKeyboardButton(text="💬 التواصل مع الدعم الفني", url=SUPPORT_URL)]
        ])
        
        text_msg = (
            f"✅ <b>تم دراسة طلبك البرمجي!</b>\n\n"
            f"{discount_text}"
            f"📌 <b>التفاصيل:</b> {details}\n"
            f"💰 <b>التكلفة المطلوبة:</b> {price_usd}$ (أو {price_stars} نجمة تلجرام)\n\n"
            f"اختر وسيلة الدفع المناسبة بالأسفل للاستلام الفوري:"
        )
        
        await message.answer(text_msg, reply_markup=keyboard, parse_mode="HTML")
        
    except Exception as e:
        logging.error(f"❌ Error processing request: {e}\n{traceback.format_exc()}")
        await message.answer(
            "⚠️ <b>تعذر معالجة الطلب حالياً.</b>\nإذا واجهتك أي مشكلة، تواصل مباشرة مع الدعم الفني:",
            reply_markup=SUPPORT_KEYBOARD,
            parse_mode="HTML"
        )

# ==========================================
# 6. معالجة دفع نجوم تلجرام (Telegram Stars)
# ==========================================

@dp.callback_query(F.data.startswith("buy_stars_"))
async def process_stars_payment(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    req_data = user_requests.get(user_id)
    
    if not req_data:
        await callback.answer("⚠️ لم يتم العثور على طلب معلق. يرجى إرسال طلبك مجدداً.", show_alert=True)
        return
        
    price_stars = req_data["price_stars"]
    prices = [LabeledPrice(label=req_data["details"], amount=price_stars)]
    
    await bot.send_invoice(
        chat_id=callback.message.chat.id,
        title="طلب كود برمجي - MISTX",
        description=f"تسليم كود مخصص: {req_data['details']}",
        payload=f"stars_order_{user_id}",
        provider_token="",
        currency="XTR",
        prices=prices
    )
    await callback.answer()

@dp.pre_checkout_query()
async def process_pre_checkout(pre_checkout_query: PreCheckoutQuery):
    await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)

@dp.message(F.successful_payment)
async def process_successful_payment(message: types.Message):
    user_id = message.from_user.id
    req_data = user_requests.get(user_id)
    
    if req_data:
        prompt = req_data["prompt"]
        user_active_promo.pop(user_id, None)
        await message.answer("🎉 <b>تم استلام الدفع بنجاح!</b> جاري تحضير طلبك...", parse_mode="HTML")
        await generate_and_send_code(prompt, message)
    else:
        await message.answer("✅ تم استلام الدفع، شكرًا لك!")

# ==========================================
# 7. التشغيل الرئيسي
# ==========================================

async def main():
    print("🚀 جاري تشغيل بوت MISTX...")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
