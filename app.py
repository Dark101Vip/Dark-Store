from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from flask_wtf.csrf import CSRFProtect, CSRFError, generate_csrf
from datetime import datetime, timedelta
import os
import re
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from PIL import Image
import requests
import json

# ==================== إعداد التطبيق ====================
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY") or os.urandom(32).hex()
app.config['WTF_CSRF_SECRET_KEY'] = os.environ.get('WTF_CSRF_SECRET_KEY', app.secret_key)
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    REMEMBER_COOKIE_HTTPONLY=True,
    PREFERRED_URL_SCHEME='https'
)
csrf = CSRFProtect(app)

@app.errorhandler(CSRFError)
def handle_csrf_error(e):
    flash('تم اكتشاف طلب غير صالح. يرجى إعادة المحاولة.', 'error')
    return redirect(request.referrer or url_for('index'))

@app.after_request
def set_security_headers(response):
    response.headers.setdefault('X-Content-Type-Options', 'nosniff')
    response.headers.setdefault('X-Frame-Options', 'SAMEORIGIN')
    response.headers.setdefault('Referrer-Policy', 'strict-origin-when-cross-origin')
    response.headers.setdefault('X-XSS-Protection', '1; mode=block')
    if request.is_secure:
        response.headers.setdefault('Strict-Transport-Security', 'max-age=63072000; includeSubDomains; preload')
    return response

@app.context_processor
def inject_globals():
    return {
        'csrf_token': generate_csrf,
        'get_cart': get_cart
    }

# ==================== إعداد رفع الصور ====================
UPLOAD_FOLDER = 'static/uploads'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
MAX_CONTENT_LENGTH = 5 * 1024 * 1024  # 5 ميجابايت

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = MAX_CONTENT_LENGTH

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# ==================== إعداد تليجرام ====================
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "YOUR_CHAT_ID_HERE")

def send_telegram_message(message):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            'chat_id': TELEGRAM_CHAT_ID,
            'text': message,
            'parse_mode': 'HTML'
        }
        response = requests.post(url, json=payload)
        return response.ok
    except Exception as e:
        print(f"خطأ في إرسال تليجرام: {e}")
        return False

# ==================== إعداد قاعدة البيانات ====================
database_url = os.environ.get("DATABASE_URL")
if database_url and database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)

app.config["SQLALCHEMY_DATABASE_URI"] = database_url or "sqlite:///mahally.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
    "pool_size": 5,
    "pool_recycle": 300,
}

db = SQLAlchemy(app)

# ==================== إعداد نظام تسجيل الدخول ====================
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message = 'يرجى تسجيل الدخول أولاً'
login_manager.login_message_category = 'error'

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# ==================== نماذج قاعدة البيانات ====================

class User(UserMixin, db.Model):
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    phone = db.Column(db.String(20), unique=True, nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=True)
    password_hash = db.Column(db.String(200), nullable=True)
    role = db.Column(db.String(20), default='customer')
    is_subscribed = db.Column(db.Boolean, default=False)
    subscription_expiry = db.Column(db.Date, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Product(db.Model):
    __tablename__ = 'products'
    
    id = db.Column(db.Integer, primary_key=True)
    merchant_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    merchant = db.relationship('User', backref='products')
    name = db.Column(db.String(200), nullable=False)
    category = db.Column(db.String(50))
    price = db.Column(db.Float, nullable=False)
    quantity = db.Column(db.Integer, default=0)
    description = db.Column(db.Text)
    image_filename = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Order(db.Model):
    __tablename__ = 'orders'
    
    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    customer_name = db.Column(db.String(100), nullable=False)
    customer_phone = db.Column(db.String(20), nullable=False)
    center = db.Column(db.String(100), nullable=False)
    village = db.Column(db.String(100), nullable=False)
    address_details = db.Column(db.Text, nullable=False)
    total = db.Column(db.Float, nullable=False)
    status = db.Column(db.String(20), default='pending')
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    items = db.relationship('OrderItem', backref='order', lazy=True, cascade='all, delete-orphan')

class OrderItem(db.Model):
    __tablename__ = 'order_items'
    
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('orders.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=True)
    product_name = db.Column(db.String(200), nullable=False)
    qty = db.Column(db.Integer, nullable=False)
    price = db.Column(db.Float, nullable=False)
    merchant_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    merchant_name = db.Column(db.String(100), nullable=False)
    merchant_phone = db.Column(db.String(20), nullable=False)

class Subscription(db.Model):
    __tablename__ = 'subscriptions'
    
    id = db.Column(db.Integer, primary_key=True)
    merchant_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    merchant = db.relationship('User', backref='subscriptions')
    amount = db.Column(db.Float, nullable=False)
    start_date = db.Column(db.Date, default=datetime.utcnow)
    end_date = db.Column(db.Date, nullable=False)
    status = db.Column(db.String(20), default='active')
    payment_method = db.Column(db.String(50))
    payment_ref = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

# ===== نموذج طلبات الدفع الجديد =====
class PaymentRequest(db.Model):
    __tablename__ = 'payment_requests'
    
    id = db.Column(db.Integer, primary_key=True)
    merchant_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    merchant = db.relationship('User', foreign_keys=[merchant_id], backref='payment_requests')
    amount = db.Column(db.Float, default=50)
    sender_phone = db.Column(db.String(20), nullable=False)
    sender_name = db.Column(db.String(100), nullable=False)
    transaction_id = db.Column(db.String(100), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(20), default='pending')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    approved_at = db.Column(db.DateTime, nullable=True)
    approved_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    approver = db.relationship('User', foreign_keys=[approved_by], backref='approved_payments')

# إنشاء الجداول
with app.app_context():
    db.create_all()

# ==================== مساعدة دوال ====================

def get_cart():
    cart = session.get('cart', [])
    return cart

def set_cart(cart):
    session['cart'] = cart

def clear_cart():
    session.pop('cart', None)

def get_cart_total(cart):
    return sum(item['price'] * item['qty'] for item in cart)

# ==================== المسارات (Routes) ====================

@app.route('/')
def index():
    products = Product.query.filter(Product.quantity > 0).order_by(Product.created_at.desc()).all()
    categories = db.session.query(Product.category).distinct().all()
    categories = [c[0] for c in categories if c[0]]
    
    category_filter = request.args.get('category')
    if category_filter:
        products = [p for p in products if p.category == category_filter]
    
    search_query = request.args.get('search')
    if search_query:
        products = [p for p in products if search_query.lower() in p.name.lower() or (p.description and search_query.lower() in p.description.lower())]
    
    return render_template('index.html', 
                         products=products, 
                         categories=categories, 
                         selected_category=category_filter,
                         search_query=search_query,
                         cart=get_cart())

@app.route('/add_to_cart/<int:product_id>', methods=['POST'])
def add_to_cart(product_id):
    product = Product.query.get_or_404(product_id)
    qty = int(request.form.get('qty', 1))
    
    if qty > product.quantity:
        flash(f'الكمية المطلوبة غير متوفرة. المتاح: {product.quantity}', 'error')
        return redirect(request.referrer or url_for('index'))
    
    cart = get_cart()
    
    for item in cart:
        if item['product_id'] == product_id:
            if item['qty'] + qty > product.quantity:
                flash(f'لا يمكن إضافة أكثر من {product.quantity} من هذا المنتج', 'error')
                return redirect(request.referrer or url_for('index'))
            item['qty'] += qty
            set_cart(cart)
            flash(f'تم تحديث كمية {product.name} في السلة', 'success')
            return redirect(request.referrer or url_for('index'))
    
    cart.append({
        'product_id': product.id,
        'name': product.name,
        'price': product.price,
        'qty': qty,
        'merchant_id': product.merchant_id,
        'merchant_name': product.merchant.name,
        'merchant_phone': product.merchant.phone,
        'image_filename': product.image_filename
    })
    set_cart(cart)
    flash(f'تم إضافة {product.name} إلى السلة', 'success')
    return redirect(request.referrer or url_for('index'))

@app.route('/checkout', methods=['GET', 'POST'])
def checkout():
    cart = get_cart()
    if not cart:
        flash('السلة فارغة', 'error')
        return redirect(url_for('index'))
    
    if request.method == 'GET':
        return render_template('checkout.html', cart=cart, total=get_cart_total(cart))
    
    customer_name = request.form.get('customer_name')
    customer_phone = request.form.get('customer_phone')
    center = request.form.get('center')
    village = request.form.get('village')
    address = request.form.get('address')
    notes = request.form.get('notes', '')
    
    if not all([customer_name, customer_phone, center, village, address]):
        flash('يرجى ملء جميع البيانات المطلوبة', 'error')
        return render_template('checkout.html', cart=cart, total=get_cart_total(cart))
    
    total = get_cart_total(cart)
    
    order = Order(
        customer_id=current_user.id if current_user.is_authenticated else None,
        customer_name=customer_name,
        customer_phone=customer_phone,
        center=center,
        village=village,
        address_details=address,
        total=total,
        notes=notes,
        status='pending'
    )
    db.session.add(order)
    db.session.flush()
    
    for item in cart:
        order_item = OrderItem(
            order_id=order.id,
            product_id=item['product_id'],
            product_name=item['name'],
            qty=item['qty'],
            price=item['price'],
            merchant_id=item['merchant_id'],
            merchant_name=item['merchant_name'],
            merchant_phone=item['merchant_phone']
        )
        db.session.add(order_item)
        
        product = Product.query.get(item['product_id'])
        if product:
            product.quantity -= item['qty']
    
    db.session.commit()
    clear_cart()
    
    telegram_msg = f"""
🛒 <b>طلب جديد!</b>

👤 العميل: {customer_name}
📱 الهاتف: {customer_phone}
📍 الموقع: {center} - {village}
🏠 العنوان: {address}

📦 <b>المنتجات:</b>
"""
    for item in cart:
        telegram_msg += f"• {item['name']} × {item['qty']} = {item['price'] * item['qty']} ج.م\n"
    
    telegram_msg += f"""
💰 <b>الإجمالي: {total} ج.م</b>
📝 ملاحظات: {notes or 'لا توجد'}

🔗 رابط الطلب: {request.host_url}admin/view_order/{order.id}
"""
    
    send_telegram_message(telegram_msg)
    
    flash('تم إرسال طلبك بنجاح! سيتم التواصل معك قريباً.', 'success')
    return redirect(url_for('order_confirmation', order_id=order.id))

@app.route('/order_confirmation/<int:order_id>')
def order_confirmation(order_id):
    order = Order.query.get_or_404(order_id)
    return render_template('order_confirmation.html', order=order)

# ==================== تسجيل الدخول والتسجيل ====================

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard_redirect'))
    
    if request.method == 'POST':
        phone = request.form.get('phone')
        password = request.form.get('password')
        
        user = User.query.filter_by(phone=phone).first()
        
        if user and user.check_password(password):
            login_user(user)
            flash(f'مرحباً بك {user.name}!', 'success')
            return redirect(url_for('dashboard_redirect'))
        else:
            flash('رقم الهاتف أو كلمة المرور غير صحيحة', 'error')
    
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard_redirect'))
    
    if request.method == 'POST':
        name = request.form.get('name')
        phone = request.form.get('phone')
        email = request.form.get('email')
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')
        role = request.form.get('role', 'customer')
        
        if not all([name, phone, password, confirm_password]):
            flash('يرجى ملء جميع الحقول المطلوبة', 'error')
            return render_template('register.html')
        
        if password != confirm_password:
            flash('كلمة المرور غير متطابقة', 'error')
            return render_template('register.html')
        
        if len(password) < 6:
            flash('كلمة المرور يجب أن تكون 6 أحرف على الأقل', 'error')
            return render_template('register.html')
        
        if User.query.filter_by(phone=phone).first():
            flash('رقم الهاتف مسجل بالفعل', 'error')
            return render_template('register.html')
        
        user = User(
            name=name,
            phone=phone,
            email=email if email else None,
            role=role
        )
        user.set_password(password)
        
        db.session.add(user)
        db.session.commit()
        
        flash('تم إنشاء الحساب بنجاح! يمكنك تسجيل الدخول الآن', 'success')
        return redirect(url_for('login'))
    
    return render_template('register.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('تم تسجيل الخروج بنجاح', 'success')
    return redirect(url_for('index'))

@app.route('/dashboard')
@login_required
def dashboard_redirect():
    if current_user.role == 'admin':
        return redirect(url_for('admin_dashboard'))
    elif current_user.role == 'merchant':
        return redirect(url_for('merchant_dashboard'))
    else:
        return redirect(url_for('customer_dashboard'))

@app.route('/customer/dashboard')
@login_required
def customer_dashboard():
    if current_user.role != 'customer':
        return redirect(url_for('dashboard_redirect'))
    
    orders = Order.query.filter_by(customer_id=current_user.id).order_by(Order.created_at.desc()).all()
    return render_template('customer_dashboard.html', orders=orders)

# ==================== لوحة تحكم التاجر ====================

@app.route('/merchant/dashboard')
@login_required
def merchant_dashboard():
    if current_user.role not in ['merchant', 'admin']:
        flash('غير مسموح لك بالدخول', 'error')
        return redirect(url_for('index'))
    
    products = Product.query.filter_by(merchant_id=current_user.id).all()
    
    order_items = OrderItem.query.filter_by(merchant_id=current_user.id).all()
    order_ids = [item.order_id for item in order_items]
    orders = Order.query.filter(Order.id.in_(order_ids)).order_by(Order.created_at.desc()).all() if order_ids else []
    
    stats = {
        'total_products': len(products),
        'total_orders': len(orders),
        'pending_orders': len([o for o in orders if o.status == 'pending']),
        'total_revenue': sum(o.total for o in orders if o.status in ['shipped', 'completed'])
    }
    
    return render_template('merchant.html', 
                         products=products, 
                         orders=orders, 
                         stats=stats,
                         is_subscribed=current_user.is_subscribed)

@app.route('/merchant/subscribe', methods=['GET', 'POST'])
@login_required
def merchant_subscribe():
    if current_user.role not in ['merchant', 'admin']:
        flash('غير مسموح', 'error')
        return redirect(url_for('merchant_dashboard'))
    
    if current_user.is_subscribed:
        flash('أنت مشترك بالفعل!', 'success')
        return redirect(url_for('merchant_dashboard'))
    
    VODAFONE_CASH_NUMBER = os.environ.get('VODAFONE_CASH_NUMBER', '01000000000')
    
    if request.method == 'POST':
        sender_phone = request.form.get('sender_phone')
        sender_name = request.form.get('sender_name')
        transaction_id = request.form.get('transaction_id')
        notes = request.form.get('notes', '')
        
        if not all([sender_phone, sender_name, transaction_id]):
            flash('يرجى ملء جميع الحقول المطلوبة', 'error')
            return render_template('subscribe.html', vodafone_number=VODAFONE_CASH_NUMBER)
        
        payment = PaymentRequest(
            merchant_id=current_user.id,
            amount=50,
            sender_phone=sender_phone,
            sender_name=sender_name,
            transaction_id=transaction_id,
            notes=notes,
            status='pending'
        )
        db.session.add(payment)
        db.session.commit()
        
        telegram_msg = f"""
💰 <b>طلب اشتراك جديد!</b>

👤 التاجر: {current_user.name}
📱 هاتف التاجر: {current_user.phone}
📱 رقم المرسل: {sender_phone}
👤 اسم المرسل: {sender_name}
🆔 رقم العملية: {transaction_id}
📝 ملاحظات: {notes or 'لا توجد'}

🔗 رابط الموافقة: {request.host_url}admin/panel
"""
        send_telegram_message(telegram_msg)
        
        flash('تم إرسال طلب الدفع بنجاح! سيتم تفعيل اشتراكك بعد التحقق.', 'success')
        return redirect(url_for('merchant_dashboard'))
    
    return render_template('subscribe.html', vodafone_number=VODAFONE_CASH_NUMBER)

@app.route('/merchant/add_product', methods=['POST'])
@login_required
def merchant_add_product():
    if current_user.role not in ['merchant', 'admin']:
        flash('غير مسموح', 'error')
        return redirect(url_for('merchant_dashboard'))
    
    if not current_user.is_subscribed and current_user.role == 'merchant':
        flash('يجب تفعيل الاشتراك الشهري أولاً', 'error')
        return redirect(url_for('merchant_dashboard'))
    
    name = request.form.get('name')
    category = request.form.get('category')
    price = request.form.get('price')
    quantity = request.form.get('quantity')
    description = request.form.get('description', '')
    
    if not all([name, category, price, quantity]):
        flash('يرجى ملء جميع الحقول المطلوبة', 'error')
        return redirect(url_for('merchant_dashboard'))
    
    image_filename = None
    if 'product_image' in request.files:
        file = request.files['product_image']
        if file and file.filename and allowed_file(file.filename):
            timestamp = datetime.utcnow().strftime('%Y%m%d%H%M%S')
            filename = secure_filename(file.filename)
            image_filename = f"{timestamp}_{filename}"
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], image_filename)
            file.save(filepath)
            
            try:
                img = Image.open(filepath)
                img.thumbnail((500, 500))
                img.save(filepath, optimize=True, quality=85)
            except:
                pass
    
    try:
        product = Product(
            merchant_id=current_user.id,
            name=name,
            category=category,
            price=float(price),
            quantity=int(quantity),
            description=description,
            image_filename=image_filename
        )
        db.session.add(product)
        db.session.commit()
        flash('تم إضافة المنتج بنجاح!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'حدث خطأ: {str(e)}', 'error')
    
    return redirect(url_for('merchant_dashboard'))

@app.route('/merchant/update_order_status/<int:order_id>', methods=['POST'])
@login_required
def merchant_update_order_status(order_id):
    if current_user.role not in ['merchant', 'admin']:
        return jsonify({'error': 'غير مسموح'}), 403
    
    order = Order.query.get_or_404(order_id)
    
    order_item = OrderItem.query.filter_by(order_id=order_id, merchant_id=current_user.id).first()
    if not order_item and current_user.role != 'admin':
        flash('هذا الطلب لا يخصك', 'error')
        return redirect(url_for('merchant_dashboard'))
    
    status = request.form.get('status')
    
    if status not in ['pending', 'accepted', 'rejected', 'shipped', 'completed', 'cancelled']:
        flash('حالة غير صالحة', 'error')
        return redirect(url_for('merchant_dashboard'))
    
    old_status = order.status
    order.status = status
    order.updated_at = datetime.utcnow()
    db.session.commit()
    
    status_names = {
        'pending': 'قيد الانتظار',
        'accepted': 'تم القبول',
        'rejected': 'مرفوض',
        'shipped': 'تم الشحن',
        'completed': 'تم التوصيل',
        'cancelled': 'ملغي'
    }
    
    telegram_msg = f"""
📦 <b>تحديث حالة الطلب #{order.id}</b>

📌 الحالة القديمة: {status_names.get(old_status, old_status)}
📌 الحالة الجديدة: <b>{status_names.get(status, status)}</b>

👤 العميل: {order.customer_name}
📱 الهاتف: {order.customer_phone}
💰 المبلغ: {order.total} ج.م
🛒 التاجر: {current_user.name}

🔗 رابط الطلب: {request.host_url}admin/view_order/{order.id}
"""
    send_telegram_message(telegram_msg)
    
    flash(f'تم تحديث حالة الطلب #{order.id} إلى: {status_names.get(status, status)}', 'success')
    return redirect(url_for('merchant_dashboard'))

@app.route('/merchant/delete_product/<int:product_id>', methods=['POST'])
@login_required
def merchant_delete_product(product_id):
    product = Product.query.get_or_404(product_id)
    
    if product.merchant_id != current_user.id and current_user.role != 'admin':
        flash('غير مسموح لك بحذف هذا المنتج', 'error')
        return redirect(url_for('merchant_dashboard'))
    
    if product.image_filename:
        try:
            os.remove(os.path.join(app.config['UPLOAD_FOLDER'], product.image_filename))
        except:
            pass
    
    db.session.delete(product)
    db.session.commit()
    flash('تم حذف المنتج بنجاح', 'success')
    return redirect(url_for('merchant_dashboard'))

# ==================== لوحة تحكم المدير (العامة) ====================

@app.route('/admin/dashboard')
@login_required
def admin_dashboard():
    if current_user.role != 'admin':
        flash('غير مسموح لك بالدخول', 'error')
        return redirect(url_for('index'))
    
    orders = Order.query.order_by(Order.created_at.desc()).all()
    total_orders = len(orders)
    pending_orders = len([o for o in orders if o.status == 'pending'])
    accepted_orders = len([o for o in orders if o.status == 'accepted'])
    shipped_orders = len([o for o in orders if o.status == 'shipped'])
    completed_orders = len([o for o in orders if o.status == 'completed'])
    rejected_orders = len([o for o in orders if o.status == 'rejected'])
    
    total_revenue = db.session.query(db.func.sum(Order.total)).filter(Order.status.in_(['shipped', 'completed'])).scalar() or 0
    
    total_merchants = User.query.filter_by(role='merchant').count()
    active_merchants = User.query.filter_by(role='merchant', is_subscribed=True).count()
    total_products = Product.query.count()
    total_customers = User.query.filter_by(role='customer').count()
    
    stats = {
        'total_orders': total_orders,
        'pending_orders': pending_orders,
        'accepted_orders': accepted_orders,
        'shipped_orders': shipped_orders,
        'completed_orders': completed_orders,
        'rejected_orders': rejected_orders,
        'total_revenue': total_revenue,
        'total_merchants': total_merchants,
        'active_merchants': active_merchants,
        'total_products': total_products,
        'total_customers': total_customers
    }
    
    recent_orders = orders[:10]
    users = User.query.order_by(User.created_at.desc()).all()
    
    return render_template('admin.html', orders=recent_orders, stats=stats, all_orders=orders, users=users)

@app.route('/admin/update_order/<int:order_id>', methods=['POST'])
@login_required
def admin_update_order(order_id):
    if current_user.role != 'admin':
        return jsonify({'error': 'غير مسموح'}), 403
    
    order = Order.query.get_or_404(order_id)
    status = request.form.get('status')
    
    if status not in ['pending', 'accepted', 'rejected', 'shipped', 'completed', 'cancelled']:
        flash('حالة غير صالحة', 'error')
        return redirect(url_for('admin_dashboard'))
    
    order.status = status
    order.updated_at = datetime.utcnow()
    db.session.commit()
    
    status_names = {
        'pending': 'قيد الانتظار',
        'accepted': 'تم القبول',
        'rejected': 'مرفوض',
        'shipped': 'تم الشحن',
        'completed': 'تم التوصيل',
        'cancelled': 'ملغي'
    }
    
    flash(f'تم تحديث حالة الطلب #{order.id} إلى: {status_names.get(status, status)}', 'success')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/view_order/<int:order_id>')
@login_required
def admin_view_order(order_id):
    if current_user.role != 'admin':
        flash('غير مسموح', 'error')
        return redirect(url_for('index'))
    
    order = Order.query.get_or_404(order_id)
    return render_template('order_details.html', order=order)

@app.route('/admin/manage_users')
@login_required
def admin_manage_users():
    if current_user.role != 'admin':
        flash('غير مسموح', 'error')
        return redirect(url_for('index'))
    
    users = User.query.order_by(User.created_at.desc()).all()
    return render_template('admin_users.html', users=users)

@app.route('/admin/toggle_merchant_subscription/<int:user_id>', methods=['POST'])
@login_required
def admin_toggle_subscription(user_id):
    if current_user.role != 'admin':
        return jsonify({'error': 'غير مسموح'}), 403
    
    user = User.query.get_or_404(user_id)
    if user.role != 'merchant':
        flash('المستخدم ليس تاجراً', 'error')
        return redirect(url_for('admin_manage_users'))
    
    user.is_subscribed = not user.is_subscribed
    if user.is_subscribed:
        user.subscription_expiry = datetime.utcnow().date() + timedelta(days=30)
    else:
        user.subscription_expiry = None
    
    db.session.commit()
    flash(f'تم {"تفعيل" if user.is_subscribed else "إلغاء"} اشتراك {user.name}', 'success')
    return redirect(url_for('admin_manage_users'))

# ==================== لوحة تحكم المدير (الخاصة) ====================

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    """صفحة تسجيل دخول المدير الخاصة"""
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        admin_username = os.environ.get('ADMIN_USERNAME', 'admin')
        admin_password = os.environ.get('ADMIN_PASSWORD', '123456')
        
        if username == admin_username and password == admin_password:
            session['admin_logged_in'] = True
            flash('مرحباً بك في لوحة تحكم المدير!', 'success')
            return redirect(url_for('admin_panel'))
        else:
            flash('اسم المستخدم أو كلمة المرور غير صحيحة', 'error')
    
    return render_template('admin_login.html')

@app.route('/admin/panel')
def admin_panel():
    """لوحة تحكم المدير الخاصة"""
    if not session.get('admin_logged_in'):
        flash('يرجى تسجيل الدخول أولاً', 'error')
        return redirect(url_for('admin_login'))
    
    pending_payments = PaymentRequest.query.filter_by(status='pending').order_by(PaymentRequest.created_at.desc()).all()
    orders = Order.query.order_by(Order.created_at.desc()).all()
    products = Product.query.order_by(Product.created_at.desc()).all()
    users = User.query.order_by(User.created_at.desc()).all()
    
    stats = {
        'total_orders': len(orders),
        'pending_orders': len([o for o in orders if o.status == 'pending']),
        'total_products': len(products),
        'total_users': len(users),
        'pending_payments': len(pending_payments),
        'total_revenue': db.session.query(db.func.sum(Order.total)).filter(Order.status.in_(['shipped', 'completed'])).scalar() or 0
    }
    
    return render_template('admin_panel.html', 
                         pending_payments=pending_payments,
                         orders=orders,
                         products=products,
                         users=users,
                         stats=stats)

@app.route('/admin/approve_payment/<int:payment_id>', methods=['POST'])
def admin_approve_payment(payment_id):
    """الموافقة على طلب دفع وتفعيل اشتراك التاجر"""
    if not session.get('admin_logged_in'):
        flash('يرجى تسجيل الدخول أولاً', 'error')
        return redirect(url_for('admin_login'))
    
    payment = PaymentRequest.query.get_or_404(payment_id)
    
    if payment.status != 'pending':
        flash('هذا الطلب تم معالجته بالفعل', 'error')
        return redirect(url_for('admin_panel'))
    
    merchant = User.query.get(payment.merchant_id)
    if merchant:
        merchant.is_subscribed = True
        merchant.subscription_expiry = datetime.utcnow().date() + timedelta(days=30)
    
    payment.status = 'approved'
    payment.approved_at = datetime.utcnow()
    db.session.commit()
    
    telegram_msg = f"""
✅ <b>تم تفعيل اشتراكك!</b>

👤 التاجر: {merchant.name}
📱 الهاتف: {merchant.phone}
💰 المبلغ: 50 ج.م
📅 تاريخ التفعيل: {datetime.utcnow().strftime('%Y-%m-%d')}
📅 ينتهي في: {merchant.subscription_expiry}

🎉 أصبح بإمكانك إضافة المنتجات وإدارة متجرك!
"""
    send_telegram_message(telegram_msg)
    
    flash(f'تم تفعيل اشتراك {merchant.name} بنجاح!', 'success')
    return redirect(url_for('admin_panel'))

@app.route('/admin/reject_payment/<int:payment_id>', methods=['POST'])
def admin_reject_payment(payment_id):
    """رفض طلب دفع"""
    if not session.get('admin_logged_in'):
        flash('يرجى تسجيل الدخول أولاً', 'error')
        return redirect(url_for('admin_login'))
    
    payment = PaymentRequest.query.get_or_404(payment_id)
    
    if payment.status != 'pending':
        flash('هذا الطلب تم معالجته بالفعل', 'error')
        return redirect(url_for('admin_panel'))
    
    payment.status = 'rejected'
    db.session.commit()
    
    flash('تم رفض طلب الدفع', 'success')
    return redirect(url_for('admin_panel'))

@app.route('/admin/logout')
def admin_logout():
    """تسجيل خروج المدير"""
    session.pop('admin_logged_in', None)
    flash('تم تسجيل الخروج بنجاح', 'success')
    return redirect(url_for('admin_login'))

# ==================== PWA Routes ====================

@app.route('/sw.js')
def serve_sw():
    """Serve service worker"""
    response = send_from_directory('static', 'sw.js')
    response.headers['Cache-Control'] = 'no-cache'
    response.headers['Service-Worker-Allowed'] = '/'
    return response

@app.route('/manifest.json')
def serve_manifest():
    """Serve manifest file"""
    return send_from_directory('static', 'manifest.json')

# ==================== تشغيل التطبيق ====================
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)