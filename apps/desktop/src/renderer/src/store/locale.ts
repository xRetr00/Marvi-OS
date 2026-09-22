import { atom } from 'nanostores'
import { persistString, storedString } from '../lib/storage'

export type InterfaceLocale = 'en' | 'ar'
const LOCALE_KEY = 'marvi.desktop.interface.locale.v1'

export const $interfaceLocale = atom<InterfaceLocale>(
  typeof window !== 'undefined' && storedString(LOCALE_KEY) === 'ar' ? 'ar' : 'en'
)

export function setInterfaceLocale(locale: InterfaceLocale): void {
  $interfaceLocale.set(locale)
}

export function syncLocaleStorage(key: string, value: string | null): boolean {
  if (key !== LOCALE_KEY || (value !== 'en' && value !== 'ar')) return false
  $interfaceLocale.set(value)
  return true
}

export function applyInterfaceLocale(root: HTMLElement, locale: InterfaceLocale): void {
  root.lang = locale
  root.dir = locale === 'ar' ? 'rtl' : 'ltr'
  root.dataset.locale = locale
}

// English is the lookup key and the visible fallback while the catalogue grows.
const arabic: Record<string, string> = {
  Core: 'الأساسيات',
  Context: 'السياق',
  Cortex: 'الذاكرة',
  Capabilities: 'الإمكانات',
  Overview: 'نظرة عامة',
  Voice: 'الصوت',
  Chat: 'الدردشة',
  Vision: 'الرؤية',
  Room: 'الغرفة',
  Activity: 'النشاط',
  Meetings: 'الاجتماعات',
  Resources: 'الموارد',
  Graph: 'الرسم البياني',
  Mind: 'العقل',
  Skills: 'المهارات',
  Cronjobs: 'المهام المجدولة',
  Workflows: 'سير العمل',
  Connectors: 'الاتصالات',
  Channels: 'القنوات',
  Plugins: 'الإضافات',
  Providers: 'المزوّدون',
  Models: 'النماذج',
  Usage: 'الاستخدام',
  Memory: 'الذاكرة',
  Workspace: 'مساحة العمل',
  Appearance: 'المظهر',
  Preferences: 'التفضيلات',
  About: 'حول',
  Themes: 'السمات',
  Fonts: 'الخطوط',
  Window: 'النافذة',
  'Dynamic Island': 'الجزيرة الديناميكية',
  'Desktop companion': 'رفيق سطح المكتب',
  'Speech recognition': 'التعرّف على الكلام',
  'Voice synthesis': 'توليد الصوت',
  'Wake word': 'كلمة التنبيه',
  Settings: 'الإعدادات',
  'Settings sections': 'أقسام الإعدادات',
  'Close settings': 'إغلاق الإعدادات',
  'Main navigation': 'التنقّل الرئيسي',
  'Maintenance terminals': 'أدوات الصيانة',
  'LOCAL INTELLIGENCE': 'ذكاء محلي',
  'Check system': 'فحص النظام',
  'Run setup': 'تشغيل الإعداد',
  'List models': 'عرض النماذج',
  Diagnostics: 'التشخيص',
  'Interface language': 'لغة الواجهة',
  Language: 'اللغة',
  English: 'الإنجليزية',
  Arabic: 'العربية',
  'Arabic changes the app and chat interface. Speech language is configured separately.':
    'تغيّر العربية واجهة التطبيق والدردشة. تُضبط لغة الكلام بشكل منفصل.',
  'Marvi OS settings': 'إعدادات Marvi OS',
  'Manage local services, action approval, and connected devices.':
    'إدارة الخدمات المحلية والموافقة على الإجراءات والأجهزة المتصلة.',
  Runtime: 'وقت التشغيل',
  'Keyboard shortcuts': 'اختصارات لوحة المفاتيح',
  Open: 'فتح',
  'Global shortcuts': 'الاختصارات العامة',
  'Confirmation mode': 'وضع التأكيد',
  'Action approval': 'الموافقة على الإجراءات',
  'Privacy mode': 'وضع الخصوصية',
  'Keep everything on this machine': 'الاحتفاظ بكل شيء على هذا الجهاز',
  'Device status': 'حالة الأجهزة',
  Microphone: 'الميكروفون',
  Camera: 'الكاميرا',
  Gateway: 'البوابة',
  'NO PROVIDER CONNECTED — OPEN PROVIDERS TO CONNECT ONE':
    'لا يوجد مزوّد متصل — افتح صفحة المزوّدين لإضافة واحد',
  'Chat session metrics': 'مقاييس جلسة الدردشة',
  'Chat sessions': 'المحادثات',
  'Thread title': 'عنوان المحادثة',
  'Rename thread': 'إعادة تسمية المحادثة',
  'Archive thread': 'أرشفة المحادثة',
  'Export as Markdown': 'تصدير بصيغة Markdown',
  'Export thread as Markdown': 'تصدير المحادثة بصيغة Markdown',
  'Delete thread': 'حذف المحادثة',
  'Start a new conversation': 'بدء محادثة جديدة',
  'New conversation': 'محادثة جديدة',
  'NEW CHAT': 'محادثة جديدة',
  'Search conversations': 'البحث في المحادثات',
  RECENT: 'الأخيرة',
  'NO MATCHING CONVERSATIONS': 'لا توجد محادثات مطابقة',
  'NO CONVERSATIONS YET': 'لا توجد محادثات بعد',
  'Telegram conversations': 'محادثات Telegram',
  'Export conversation as Markdown': 'تصدير المحادثة بصيغة Markdown',
  EXPORT: 'تصدير',
  'CONTROL CENTER': 'مركز التحكم',
  msgs: 'رسائل',
  'What should we work through?': 'بماذا نبدأ؟',
  'One assistant across voice, memory, tools, and the room.':
    'مساعد واحد للصوت والذاكرة والأدوات والغرفة.',
  'Starter prompts': 'اقتراحات للبدء',
  'What is happening in the room right now?': 'ما الذي يحدث في الغرفة الآن؟',
  'What do you remember that could help me today?': 'ماذا تتذكر مما قد يساعدني اليوم؟',
  'Help me turn my next goal into a clear plan.': 'ساعدني على تحويل هدفي التالي إلى خطة واضحة.',
  PLAN: 'خطة',
  MEMORY: 'الذاكرة',
  'Scroll to latest message': 'الانتقال إلى أحدث رسالة',
  'Message Marvi': 'مراسلة Marvi',
  'Send a message…': 'اكتب رسالة…',
  'Connect a provider to chat': 'أضف مزوّدًا لبدء الدردشة',
  'Attach images or documents': 'إرفاق صور أو مستندات',
  Send: 'إرسال',
  Stop: 'إيقاف',
  ROOM: 'الغرفة',
  'Marvi OS ready': 'Marvi OS جاهز',
  'Action confirmation': 'تأكيد الإجراء',
  CONFIRM: 'تأكيد',
  DENY: 'رفض',
  'WAIT…': 'انتظر…',
  APPROVE: 'موافقة',
  NOW: 'الآن',
  READY: 'جاهز',
  AWAKE: 'منتبه',
  LISTEN: 'يستمع',
  THINK: 'يفكر',
  SPEAK: 'يتحدث',
  WORKING: 'يعمل',
  NOTICE: 'تنبيه',
  OFFLINE: 'غير متصل',
  'Confirm · ask me': 'تأكيد · اسألني',
  'YOLO · auto accept': 'YOLO · قبول تلقائي',
  'On · nothing leaves': 'تشغيل · لا يغادر شيء',
  'Off · normal': 'إيقاف · عادي',
  'Live room': 'الغرفة الآن',
  'Room state unavailable': 'حالة الغرفة غير متاحة',
  'Devices and presence': 'الأجهزة والتواجد',
  'Recent room events': 'أحداث الغرفة الأخيرة',
  'No room events yet': 'لا توجد أحداث للغرفة بعد',
  'Live perception': 'الإدراك المباشر',
  'Vision state unavailable': 'حالة الرؤية غير متاحة',
  'Face identity': 'التعرّف على الوجوه',
  'Recent observations': 'الملاحظات الأخيرة',
  'No vision observations yet': 'لا توجد ملاحظات للرؤية بعد',
  'Where memory lives': 'مكان حفظ الذاكرة',
  'Memory provider': 'مزوّد الذاكرة',
  'How recall works': 'كيفية الاسترجاع',
  'Deciding what to remember': 'اختيار ما يجب تذكره',
  'Reading the memories': 'قراءة الذكريات',
  'Searching by meaning': 'البحث بالمعنى',
  Model: 'النموذج',
  'Marvi Cortex Memory': 'ذاكرة Marvi Cortex',
  Entries: 'الإدخالات',
  'Knowledge graph': 'رسم المعرفة',
  'Import from another assistant': 'استيراد من مساعد آخر',
  'Ask it to write down everything it knows': 'اطلب منه كتابة كل ما يعرفه',
  'Before importing': 'قبل الاستيراد',
  'Memories found': 'الذكريات الموجودة',
  'Refused as credentials': 'رُفضت لأنها بيانات اعتماد',
  Imported: 'تم الاستيراد',
  Refused: 'مرفوض',
  'Stored memories': 'الذكريات المحفوظة',
  'Nothing remembered yet': 'لا توجد ذكريات محفوظة بعد',
  'No match': 'لا توجد نتائج',
  'Loading providers': 'جارٍ تحميل المزوّدين',
  "Marvi's DMN": 'هوية Marvi',
  'DMN identity files': 'ملفات الهوية',
  'Prompt budget': 'ميزانية التعليمات',
  'Restart after a crash': 'إعادة التشغيل بعد التعطل',
  'The listener has stopped': 'توقف المستمع',
  'Loading plugins': 'جارٍ تحميل الإضافات',
  'Installed and available': 'المثبت والمتاح',
  'No plugins declared': 'لم تُعرّف إضافات',
  'Plugin storage': 'تخزين الإضافات',
  'Installed skills': 'المهارات المثبتة',
  'Loading skill store': 'جارٍ تحميل متجر المهارات',
  'Could not reach the skill store': 'تعذر الاتصال بمتجر المهارات',
  'No skills available': 'لا توجد مهارات متاحة',
  'No matching skills': 'لا توجد مهارات مطابقة',
  'Nothing here yet': 'لا يوجد شيء هنا بعد',
  Announcer: 'المذيع',
  'Voice cloning': 'استنساخ الصوت',
  'Announcer voice': 'صوت المذيع',
  'Clone a voice for her': 'استنساخ صوت لها',
  Engine: 'المحرك',
  'Add a voice': 'إضافة صوت',
  Display: 'الشاشة',
  'Local store': 'المتجر المحلي',
  'Dark themes': 'السمات الداكنة',
  'Interface type': 'خط الواجهة',
  Style: 'النمط',
  'Previous version': 'الإصدار السابق',
  'Next version': 'الإصدار التالي',
  'Your message': 'رسالتك',
  YOU: 'أنت',
  'Edit and branch from this message': 'تعديل الرسالة وفتح فرع منها',
  'Edit message': 'تعديل الرسالة',
  'Copy message': 'نسخ الرسالة',
  CANCEL: 'إلغاء',
  'SEND EDIT': 'إرسال التعديل',
  'Marvi response': 'رد Marvi',
  'Stop reading': 'إيقاف القراءة',
  'Read aloud': 'قراءة بصوت عالٍ',
  'Regenerate on a new branch': 'إعادة الإنشاء في فرع جديد',
  'Regenerate response': 'إعادة إنشاء الرد',
  'Copy response': 'نسخ الرد',
  'Marvi starts these itself. When one will not start, the reason is its own output — shown here rather than discarded.':
    'تشغّل Marvi هذه الخدمات بنفسها. إذا تعذّر تشغيل إحداها، يظهر سبب الخطأ هنا.',
  'Talk to Marvi, stop her, open Chat or show the window — from anywhere in Windows, whether or not Marvi has focus.':
    'تحدّث إلى Marvi أو أوقفها أو افتح الدردشة أو النافذة من أي مكان في Windows.',
  'Confirm asks before actions when the model decides approval is needed. YOLO bypasses every prompt.':
    'يطلب وضع التأكيد الموافقة عندما يراها النموذج ضرورية. يتجاوز وضع YOLO كل طلبات الموافقة.',
  'Switches off web search, connected accounts, Telegram, hosted memory and update checks, and requires a local model for every call. Your own MCP servers are not affected.':
    'يعطّل البحث على الويب والحسابات المتصلة وTelegram والذاكرة المستضافة وفحص التحديثات، ويتطلب نموذجًا محليًا لكل طلب. لا تتأثر خوادم MCP الخاصة بك.'
}

export function t(message: string, locale = $interfaceLocale.get()): string {
  return locale === 'ar' ? (arabic[message] ?? message) : message
}

export function formatNumber(value: number, locale = $interfaceLocale.get()): string {
  return new Intl.NumberFormat(locale === 'ar' ? 'ar-EG' : 'en-US').format(value)
}

export function formatDate(
  value: Date | number,
  options: Intl.DateTimeFormatOptions,
  locale = $interfaceLocale.get()
): string {
  return new Intl.DateTimeFormat(locale === 'ar' ? 'ar-EG' : 'en-US', options).format(value)
}

export function formatRelative(
  value: number,
  unit: Intl.RelativeTimeFormatUnit,
  locale = $interfaceLocale.get()
): string {
  return new Intl.RelativeTimeFormat(locale === 'ar' ? 'ar-EG' : 'en-US', {
    numeric: 'auto'
  }).format(value, unit)
}

if (typeof document !== 'undefined') {
  $interfaceLocale.subscribe((locale) => {
    applyInterfaceLocale(document.documentElement, locale)
    persistString(LOCALE_KEY, locale)
  })
  window.addEventListener('storage', (event) => syncLocaleStorage(event.key ?? '', event.newValue))
}
