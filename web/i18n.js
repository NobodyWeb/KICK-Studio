/* ============================================================
   Kick Studio — runtime localization
   ------------------------------------------------------------
   Persian is the source language: every user-facing string in
   index.html / app.js is written in Persian, and this file maps
   it to English.  Static markup is translated by walking the
   DOM, dynamic strings go through t("…") in app.js.

   To add a new string: use it in the UI, then add a pair to
   I18N_EN below.  Missing entries simply stay in Persian.
   ============================================================ */
"use strict";

const I18N_LANGS = {
  fa: { label: "فارسی", short: "FA", dir: "rtl", locale: "fa-IR" },
  en: { label: "English", short: "EN", dir: "ltr", locale: "en-US" },
};

const I18N_EN = [
  /* ---------- shell / navigation ---------- */
  ["ضبط و دانلود حرفه‌ای", "Pro recording & downloads"],
  ["ضبط زنده", "Live recording"],
  ["دانلود", "Download"],
  ["VOD و کلیپ", "VOD & clips"],
  ["ضبط خودکار", "Auto recorder"],
  ["تنظیمات", "Settings"],
  ["گزارش‌ها", "Logs"],
  ["در حال بررسی…", "Checking…"],
  ["از ابتدای پخش زنده، با کیفیت دلخواه ضبط کنید.", "Record a live stream from its start, at the quality you pick."],
  ["اتصال…", "Connecting…"],
  ["متصل", "Connected"],
  ["قطع", "Offline"],
  ["در حال بارگذاری گزارش‌ها…", "Loading logs…"],
  ["زبان", "Language"],

  /* ---------- LIVE ---------- */
  ["یک کانال را برای ضبط آماده کنید", "Set up a channel for recording"],
  ["لینک کانال Kick را وارد کنید؛ کیفیت منبع و خروجی را انتخاب کنید و ضبط را شروع کنید.", "Paste a Kick channel link, choose the source and output quality, then start recording."],
  ["لینک کانال", "Channel link"],
  ["بررسی کانال", "Check channel"],
  ["این کانال لایو نیست.", "This channel is offline."],
  ["به محض لایو شدن می‌توانید ضبط را شروع کنید یا از ضبط خودکار استفاده کنید.", "Once the channel goes live you can start recording, or let the auto recorder do it."],
  ["بیننده", "viewers"],
  ["کیفیت منبع", "Source quality"],
  ["کیفیت دریافتی از Kick؛ روی حجم اینترنت و دیسک اثر می‌گذارد.", "The quality pulled from Kick; affects bandwidth and disk usage."],
  ["پروفایل خروجی", "Output profile"],
  ["تنظیمات حرفه‌ای کیفیت و بیت‌ریت", "Advanced quality & bitrate"],
  ["حداکثر ارتفاع", "Max height"],
  ["بیتریت ویدیو", "Video bitrate"],
  ["CRF (کیفیت)", "CRF (quality)"],
  ["بیتریت صدا", "Audio bitrate"],
  ["محدودیت FPS", "FPS limit"],
  ["آرگومان‌های اضافه FFmpeg (اختیاری)", "Extra FFmpeg arguments (optional)"],
  ["آرگومان‌های اضافه FFmpeg", "Extra FFmpeg arguments"],
  ["پوشه ذخیره", "Save folder"],
  ["ضبط از ابتدای پخش", "Record from the beginning"],
  ["در صورت وجود DVR، از اولین لحظه استریم ضبط می‌شود.", "When DVR is available, recording starts at the very first moment of the stream."],
  ["شروع ضبط زنده", "Start live recording"],
  ["ابتدا کانال را بررسی کنید.", "Check the channel first."],
  ["وضعیت سیستم", "System status"],
  ["ضبط فعال", "Active recordings"],
  ["فضای آزاد", "Free space"],
  ["نکته‌های سریع", "Quick tips"],
  ["برای کیفیت اصلی و بدون فشار CPU، پروفایل «کپی مستقیم» را انتخاب کنید.", "For untouched quality with no CPU load, pick the “Direct copy” profile."],
  ["اگر پخش قطع و وصل شود، هر بخش به‌صورت خودکار ادامه داده می‌شود.", "If the stream drops and returns, the recording picks up where it left off."],
  ["هر پخش زنده در یک فایل جداگانه ذخیره می‌شود؛ حتی اگر چند بار قطع شود.", "Every live session gets its own file, even across several reconnects."],
  ["ضبط‌های فعال و اخیر", "Active & recent recordings"],
  ["پاک کردن تاریخچه", "Clear history"],
  ["ضبط این کانال همین حالا فعال است.", "This channel is already being recorded."],
  ["DVR در دسترس است؛ می‌توانید از ابتدای پخش ضبط کنید.", "DVR is available; you can record from the start of the stream."],
  ["DVR در دسترس نیست؛ ضبط از لحظه فعلی آغاز می‌شود.", "DVR is not available; recording starts from the current moment."],
  ["کانال آفلاین است؛ پس از لایو شدن دوباره بررسی کنید.", "The channel is offline; check again once it goes live."],
  ["این کانال", "This channel"],
  ["الان لایو نیست.", "is offline right now."],

  /* ---------- DOWNLOAD ---------- */
  ["دانلود مستقیم VOD و کلیپ", "Download VODs & clips directly"],
  ["لینک مستقیم بگذارید یا فهرست کانال را بارگذاری کنید. دانلودها مستقل از ضبط زنده اجرا می‌شوند.", "Paste direct links or load a channel list. Downloads run independently of live recording."],
  ["ویدیو (VOD)", "Video (VOD)"],
  ["کلیپ", "Clip"],
  ["لینک‌ها", "Links"],
  ["(هر خط یک لینک)", "(one link per line)"],
  ["بررسی لینک", "Check link"],
  ["بارگذاری فهرست کانال", "Load channel list"],
  ["این هفته", "This week"],
  ["امروز", "Today"],
  ["این ماه", "This month"],
  ["همه", "All"],
  ["انتخاب همه", "Select all"],
  ["لغو انتخاب", "Clear selection"],
  ["موردی انتخاب نشده", "Nothing selected"],
  ["تنظیمات دانلود", "Download settings"],
  ["خودکار (بهترین کیفیت)", "Auto (best quality)"],
  ["برای لینک مستقیم، در صورت وجود، همه کیفیت‌ها نمایش داده می‌شوند.", "For direct links, every available quality is listed."],
  ["دانلودهای فعال و اخیر", "Active & recent downloads"],

  /* ---------- AUTO ---------- */
  ["ضبط خودکار استریمرها", "Auto-record streamers"],
  ["استریمرها را یک بار اضافه کنید؛ هر زمان لایو شوند با تنظیمات خودشان ضبط می‌شوند.", "Add streamers once; whenever they go live they are recorded with their own settings."],
  ["فعال", "On"],
  ["افزودن استریمر", "Add streamer"],
  ["بهترین موجود", "Best available"],
  ["حداکثر 1080p", "Up to 1080p"],
  ["حداکثر 720p", "Up to 720p"],
  ["حداکثر 480p", "Up to 480p"],
  ["حداکثر 360p", "Up to 360p"],
  ["کمترین", "Lowest"],
  ["افزودن", "Add"],
  ["بازه بررسی (ثانیه)", "Check interval (s)"],
  ["مهلت قطعی (ثانیه)", "Offline grace (s)"],
  ["حداکثر ضبط همزمان", "Max concurrent recordings"],
  ["ذخیره", "Save"],
  ["بررسی فوری", "Check now"],
  ["رویدادهای ضبط خودکار", "Auto-recorder activity"],
  ["استریمر", "Streamer"],
  ["ویرایش", "Edit"],
  ["حذف", "Delete"],
  ["فعال/غیرفعال", "Enable / disable"],
  ["توقف ضبط", "Stop recording"],
  ["لایو", "Live"],
  ["آفلاین", "Offline"],
  ["انتظار", "Waiting"],
  ["در صف", "Queued"],
  ["سرویس فعال", "Service running"],
  ["سرویس متوقف", "Service stopped"],
  ["در حال بررسی…", "Checking…"],
  ["بررسی در راه است", "Check coming up"],
  ["پوشه پیش‌فرض", "Default folder"],
  ["حداقل ۱۰ ثانیه", "At least 10 seconds"],

  /* ---------- SETTINGS ---------- */
  ["تنظیمات برنامه", "Application settings"],
  ["مسیر ذخیره، FFmpeg و رفتار ضبط خودکار را مدیریت کنید.", "Manage the save path, FFmpeg and auto-recorder behaviour."],
  ["پوشه پیش‌فرض دانلود", "Default download folder"],
  ["مسیر FFmpeg", "FFmpeg path"],
  ["نصب خودکار", "Auto install"],
  ["حداکثر دانلود همزمان", "Max concurrent downloads"],
  ["پروفایل خروجی پیش‌فرض", "Default output profile"],
  ["نگه داشتن فایل‌های موقت", "Keep temporary files"],
  ["فایل TS/MKV بعد از ساخت MP4 حذف نشود.", "Keep the TS/MKV files after the MP4 is built."],
  ["کوکی Kick (اختیاری)", "Kick cookie (optional)"],
  ["اگر مقداردهی شده باشد، در درخواست‌ها استفاده می‌شود.", "Used in requests when set."],
  ["ذخیره تنظیمات", "Save settings"],
  ["اطلاعات سیستم", "System info"],
  ["نسخه", "Version"],
  ["انکودرها", "Encoders"],
  ["پوشه دانلود", "Download folder"],
  ["درباره کیفیت", "About quality"],
  ["کیفیت منبع همان چیزی است که از Kick دانلود می‌شود.", "Source quality is exactly what is downloaded from Kick."],
  ["پروفایل خروجی می‌تواند فایل را کوچک‌تر کند، اما بیت‌ریت اینترنت را کم نمی‌کند.", "The output profile can shrink the file, but it does not reduce bandwidth use."],
  ["برای هر بیت‌ریت دلخواه، حالت «سفارشی» و عدد kbps را انتخاب کنید.", "For a custom bitrate, choose the “Custom” profile and enter a value in kbps."],

  /* ---------- LOGS ---------- */
  ["گزارش زنده", "Live log"],
  ["اطلاعات", "Info"],
  ["موفق", "Success"],
  ["هشدار", "Warning"],
  ["خطا", "Error"],
  ["اسکرول خودکار", "Auto-scroll"],
  ["پاک کردن", "Clear"],

  /* ---------- profiles / bitrate ---------- */
  ["کیفیت ثابت (CRF)", "Constant quality (CRF)"],
  ["حجم و کیفیت متعادل", "Balanced size and quality"],
  ["بیتریت ثابت", "Target bitrate"],
  ["حجم تقریبی مشخص", "Predictable file size"],
  ["حالت کنترل کیفیت", "Rate control mode"],
  ["خروجی نهایی", "Final output"],
  ["کپی مستقیم — کیفیت اصلی", "Direct copy — original quality"],
  ["کپی مستقیم (کیفیت اصلی)", "Direct copy (original quality)"],
  ["سفارشی — تنظیمات پیشرفته", "Custom — advanced settings"],
  ["سفارشی (پروفایل پیش‌فرض)", "Custom (default profile)"],
  ["سفارشی (حفظ شود)", "Custom (saved)"],
  ["بدون تغییر (منبع)", "Keep source"],
  ["کپی صدا", "Copy audio"],
  ["نرخ منبع", "Source frame rate"],
  ["خودکار — بهترین کیفیت", "Auto — best quality"],
  ["کم‌ترین کیفیت", "Lowest quality"],
  ["بهترین کیفیت", "Best quality"],
  ["حداکثر", "Up to"],
  ["کیفیت", "Quality"],
  ["انتخابی", "selected"],
  ["صوت کپی", "audio copy"],
  ["کپی", "Copy"],

  /* ---------- generic actions / dialogs ---------- */
  ["تأیید", "Confirm"],
  ["انصراف", "Cancel"],
  ["پاک کن", "Clear"],
  ["مسیر", "Path"],
  ["انتخاب پوشه", "Choose folder"],
  ["مسیر کامل پوشه", "Full folder path"],
  ["مسیری برای باز کردن وجود ندارد.", "There is no path to open."],
  ["مسیر مورد نظر وجود ندارد.", "That path does not exist."],
  ["ذخیره تغییرات", "Save changes"],
  ["حذف از ضبط خودکار", "Remove from auto recorder"],

  /* ---------- downloads / media ---------- */
  ["دانلود", "Download"],
  ["رسانه", "Media"],
  ["رسانه Kick", "Kick media"],
  ["لینک مستقیم", "Direct link"],
  ["کانال لایو", "Live channel"],
  ["کانال آفلاین", "Offline channel"],
  ["این کانال همین حالا لایو است", "This channel is live right now"],
  ["برای دانلود آماده است", "Ready to download"],
  ["باز کردن فایل", "Open file"],
  ["باز کردن مسیر", "Open path"],

  /* ---------- session cards ---------- */
  ["مدت", "Duration"],
  ["ضبط‌شده", "Recorded"],
  ["دانلودشده", "Downloaded"],
  ["حجم", "Size"],
  ["بخش‌ها", "Parts"],
  ["بخش", "parts"],
  ["سرعت", "Speed"],
  ["بیتریت", "Bitrate"],
  ["پیشرفت", "Progress"],
  ["مسیر:", "Path:"],
  ["فایل:", "File:"],
  ["منبع:", "Source:"],
  ["از ابتدا", "From start"],
  ["ضبط خودکار", "Auto recording"],
  ["ضبط", "recordings"],
  ["بازدید", "views"],

  /* ---------- status chips ---------- */
  ["آماده‌سازی", "Preparing"],
  ["در حال ضبط", "Recording"],
  ["نهایی‌سازی", "Finalizing"],
  ["ذخیره شد", "Saved"],
  ["متوقف", "Stopped"],
  ["بررسی لینک", "Resolving link"],
  ["در حال دانلود", "Downloading"],
  ["توقف", "Stopping"],
  ["ساخت MP4", "Building MP4"],
  ["کامل شد", "Completed"],
  ["لغو شد", "Canceled"],

  /* ---------- toasts / errors ---------- */
  ["ارتباط با سرویس داخلی برنامه برقرار نشد.", "Could not reach the app's local service."],
  ["ارتباط با سرویس داخلی قطع شد.", "Lost the connection to the local service."],
  ["خطای نامشخص", "Unknown error"],
  ["FFmpeg با موفقیت نصب شد.", "FFmpeg installed successfully."],
  ["نصب FFmpeg ناموفق بود.", "FFmpeg installation failed."],
  ["FFmpeg آماده", "FFmpeg ready"],
  ["FFmpeg نصب نشده", "FFmpeg not installed"],
  ["از تنظیمات نصب کنید", "Install it from Settings"],
  ["آماده", "Ready"],
  ["نصب نشده", "Not installed"],
  ["در حال نصب FFmpeg…", "Installing FFmpeg…"],
  ["FFmpeg در دسترس نیست.", "FFmpeg is not available."],
  ["FFmpeg از قبل آماده است.", "FFmpeg is already available."],
  ["نصب FFmpeg در حال انجام است.", "FFmpeg installation is already running."],
  ["دانلود FFmpeg آغاز شد؛ پیشرفت در همین صفحه نمایش داده می‌شود.", "FFmpeg download started; progress is shown on this page."],
  ["کوکی ذخیره شده است. برای حذف، «clear» را وارد و ذخیره کنید.", "A cookie is saved. To remove it, enter “clear” and save."],
  ["لینک کانال را وارد کنید.", "Enter a channel link."],
  ["این لینک کانال نیست. برای VOD و کلیپ از صفحه دانلود استفاده کنید.", "This is not a channel link. Use the Download page for VODs and clips."],
  ["کانال لایو است و آماده ضبط می‌باشد.", "The channel is live and ready to record."],
  ["این کانال الان لایو نیست.", "This channel is offline right now."],
  ["ابتدا کانال را دوباره بررسی کنید.", "Check the channel again first."],
  ["ضبط زنده آغاز شد.", "Live recording started."],
  ["درخواست توقف ثبت شد؛ در حال نهایی‌سازی فایل.", "Stop requested; finalizing the file."],
  ["حداقل یک لینک وارد کنید.", "Enter at least one link."],
  ["این کانال لایو است؛ برای ضبط از صفحه «ضبط زنده» استفاده کنید.", "This channel is live; use the “Live recording” page to record it."],
  ["این آیتم در حال پخش زنده است.", "This item is currently live."],
  ["لینک بررسی شد و آماده دانلود است.", "The link was checked and is ready to download."],
  ["فقط اولین لینک بررسی شد؛ بقیه هنگام دانلود بررسی می‌شوند.", "Only the first link was checked; the rest are resolved while downloading."],
  ["یک لینک کانال Kick وارد کنید تا فهرست بارگذاری شود.", "Enter a Kick channel link to load its list."],
  ["موردی برای این کانال پیدا نشد.", "Nothing was found for this channel."],
  ["یک لینک وارد کنید یا از فهرست کانال چند مورد انتخاب کنید.", "Enter a link or select items from the channel list."],
  ["استریمر به فهرست ضبط خودکار اضافه شد.", "Streamer added to the auto recorder."],
  ["استریمر در فهرست پیدا نشد.", "Streamer not found in the list."],
  ["تنظیمات ضبط خودکار ذخیره شد.", "Auto-recorder settings saved."],
  ["ضبط خودکار فعال شد.", "Auto recorder enabled."],
  ["ضبط خودکار غیرفعال شد.", "Auto recorder disabled."],
  ["استریمر از فهرست حذف شد.", "Streamer removed from the list."],
  ["بررسی فوری استریمرها آغاز شد.", "Checking streamers now."],
  ["ضبط خودکار این استریمر متوقف می‌شود.", "Stopping the auto recording for this streamer."],
  ["استریمر فعال شد.", "Streamer enabled."],
  ["استریمر غیرفعال شد.", "Streamer disabled."],
  ["تنظیمات استریمر ذخیره شد.", "Streamer settings saved."],
  ["تنظیمات با موفقیت ذخیره شد.", "Settings saved successfully."],
  ["تنظیمات ذخیره شد.", "Settings saved."],
  ["گزارش‌ها پاک شد.", "Logs cleared."],
  ["پاک کردن تاریخچه ضبط", "Clear recording history"],
  ["تمام ضبط‌های پایان‌یافته از فهرست حذف می‌شوند. فایل‌های ذخیره‌شده حذف نمی‌شوند.", "All finished recordings are removed from the list. Saved files are not deleted."],
  ["تاریخچه ضبط پاک شد.", "Recording history cleared."],
  ["پاک کردن تاریخچه دانلود", "Clear download history"],
  ["تمام دانلودهای پایان‌یافته از فهرست حذف می‌شوند. فایل‌های ذخیره‌شده حذف نمی‌شوند.", "All finished downloads are removed from the list. Saved files are not deleted."],
  ["تاریخچه دانلود پاک شد.", "Download history cleared."],
  ["درخواست توقف دانلود ثبت شد.", "Download stop request sent."],
  ["همه‌چیز به‌روز شد.", "Everything is up to date."],
  ["هنوز ضبطی شروع نشده است. یک کانال را بررسی و ضبط را آغاز کنید.", "No recordings yet. Check a channel and start recording."],
  ["هنوز دانلودی ثبت نشده است. لینک VOD یا کلیپ را وارد کنید.", "No downloads yet. Paste a VOD or clip link."],
  ["هنوز استریمری اضافه نشده است. لینک کانال را وارد کنید و «افزودن» را بزنید.", "No streamers yet. Enter a channel link and press “Add”."],
  ["رویدادی برای ضبط خودکار ثبت نشده است.", "No auto-recorder activity yet."],
  ["کلیپی بارگذاری نشده است. لینک کانال را وارد کنید و «بارگذاری فهرست کانال» را بزنید.", "No clips loaded. Enter a channel link and press “Load channel list”."],
  ["فهرستی بارگذاری نشده است. لینک کانال را وارد کنید و «بارگذاری فهرست کانال» را بزنید.", "No list loaded. Enter a channel link and press “Load channel list”."],
  ["گزارشی برای نمایش وجود ندارد.", "There are no log entries to show."],
  ["کیفیت منبع، پروفایل خروجی و پوشه اختصاصی این استریمر", "Source quality, output profile and folder for this streamer"],
  ["کیفیت دریافتی از Kick برای این استریمر.", "The quality pulled from Kick for this streamer."],
  ["پوشه ذخیره (اختیاری)", "Save folder (optional)"],

  /* ---------- bitrate helpers ---------- */
  ["معادل", "equals"],
  ["برای 1080p حدود ۴ تا ۸ مگابیت و برای 720p حدود ۲ تا ۴ مگابیت مناسب است.", "About 4–8 Mbps suits 1080p and 2–4 Mbps suits 720p."],
  ["عدد معتبر بین ۲۰۰ تا ۸۰۰۰۰ kbps وارد کنید.", "Enter a value between 200 and 80000 kbps."],
  ["بین ۰ تا ۵۱ (کمتر = کیفیت بالاتر)", "0 to 51 (lower means better quality)"],
  ["حالت بیت‌ریت فعال است؛ CRF استفاده نمی‌شود.", "Bitrate mode is on; CRF is ignored."],
  ["حالت CRF فعال است؛ بیت‌ریت ثابت تنظیم نشده است.", "CRF mode is on; no fixed bitrate is set."],
  ["کیفیت و حجم خروجی", "Output quality and size"],

  /* ---------- page subtitles / misc ---------- */
  ["دانلود VOD و کلیپ", "Download VODs & clips"],
  ["لینک مستقیم بدهید یا فهرست کانال را بارگذاری کنید.", "Paste a direct link or load a channel list."],
  ["هر استریمر با تنظیمات خودش، به‌محض لایو شدن ضبط می‌شود.", "Each streamer is recorded with its own settings as soon as it goes live."],
  ["مسیر ذخیره، FFmpeg و رفتار برنامه را مدیریت کنید.", "Manage the save path, FFmpeg and app behaviour."],
  ["رویدادهای برنامه، Kick و FFmpeg را زنده ببینید.", "Watch app, Kick and FFmpeg events live."],
  ["منوی اصلی", "Main menu"],
  ["به‌روزرسانی", "Refresh"],
  ["باز کردن پوشه دانلود", "Open download folder"],
  ["بازه کلیپ‌ها", "Clip range"],
  ["خودکار", "Auto"],
  ["برای محتوای محدود یا رفع محدودیت Cloudflare", "For restricted content or Cloudflare bypass"],
  ["اگر مقداردهی شده باشد، در درخواست‌های Kick استفاده می‌شود.", "Used for Kick requests when set."],
  ["همین حالا", "just now"],
  ["ثانیه پیش", "seconds ago"],
  ["دقیقه پیش", "minutes ago"],
  ["ثانیه", "s"],
  ["خطای سرور", "Server error"],
  ["الان لایو نیست.", "is offline right now."],
  ["بررسی بعدی:", "Next check:"],
  ["آخرین بررسی:", "Last check:"],
  ["مورد انتخاب شده", "selected"],
  ["مورد از کانال بارگذاری شد.", "items loaded from the channel."],
  ["دانلود در صف قرار گرفت.", "downloads queued."],
  ["کیفیت‌ها", "qualities"],
  ["«{name}» از فهرست حذف شود؟ ضبط فعال آن نیز متوقف می‌شود.", "Remove “{name}” from the list? Its active recording will be stopped too."],
  ["ویرایش {name}", "Edit {name}"],
  ["{name} · {n} ثانیه", "{name} · {n}s"],
  ["این فیلد را خالی بگذارید تا مسیر پیش‌فرض استفاده شود.", "Leave empty to use the default path."],
  ["{n} انکودر H.264", "{n} H.264 encoders"],
  ["حالت ضبط", "Recording mode"],
  ["از ابتدا تا انتها", "From the start"],
  ["فقط از زمان حال", "From now"],
  ["اگر DVR موجود باشد، از اولین لحظه پخش ضبط می‌شود و تا پایان ادامه می‌یابد.", "With DVR available, recording begins at the first moment of the stream and runs to the end."],
  ["ضبط از همین لحظه شروع می‌شود و تا پایان پخش ادامه دارد.", "Recording starts right now and continues until the stream ends."],
  ["برای حالت «از ابتدا»، DVR باید در دسترس باشد.", "The “from the start” mode requires DVR."],
  ["DVR در دسترس نیست؛ از زمان حال ضبط می‌شود.", "DVR is unavailable, so recording starts from now."],
  ["ضبط دوباره از ابتدا", "Record again from the start"],
  ["ضبط مجدد", "Re-record"],
  ["ضبط این پخش متوقف شده است.", "Recording of this broadcast was stopped."],
  ["حالت ضبط برای پخش‌های بعدی هم اعمال می‌شود.", "The mode also applies to future broadcasts."],
  ["ضبط دوباره از ابتدا آغاز شد.", "Recording restarted from the beginning."],
  ["خطای سرور ({status})", "Server error ({status})"],
  ["بررسی بعدی: {n} ثانیه", "Next check in {n}s"],
  ["آخرین بررسی: {time}", "Last check: {time}"],
  ["{n} مورد انتخاب شده", "{n} selected"],
  ["بیت‌ریت ویدیو (kbps)", "Video bitrate (kbps)"],
  ["بیت‌ریت صدا (kbps)", "Audio bitrate (kbps)"],
  ["{n} مورد از کانال بارگذاری شد.", "{n} items loaded from the channel."],
  ["{n} دانلود در صف قرار گرفت.", "{n} downloads queued."],
];

/* Normalize so a missing/extra ZWNJ or spacing never breaks a lookup. */
function i18nNormalize(text) {
  return String(text == null ? "" : text)
    .replace(/[\u200c\u200e\u200f\u202a-\u202e]/g, "")
    .replace(/\s+/g, " ")
    .trim();
}

const I18N_MAP = new Map(I18N_EN.map(([fa, en]) => [i18nNormalize(fa), en]));

let i18nLang = "fa";
let i18nObserver = null;
const i18nTextOriginals = new WeakMap();
const i18nAttrOriginals = new WeakMap();
const I18N_ATTRS = ["placeholder", "title", "aria-label"];
const I18N_SKIP = new Set(["SCRIPT", "STYLE", "NOSCRIPT", "TEXTAREA"]);

function currentLanguage() {
  return i18nLang;
}

function currentLocale() {
  return (I18N_LANGS[i18nLang] || I18N_LANGS.fa).locale;
}

/** Translate one dynamic string. Persian source -> English (or identity).
 *  ``vars`` fills ``{name}`` placeholders in the translation. */
function t(text, vars) {
  const source = String(text == null ? "" : text);
  const translated = i18nLang === "en" ? I18N_MAP.get(i18nNormalize(source)) || source : source;
  if (!vars) return translated;
  return translated.replace(/\{(\w+)\}/g, (match, key) =>
    Object.prototype.hasOwnProperty.call(vars, key) ? String(vars[key]) : match
  );
}

function isSkipped(node) {
  let el = node.nodeType === 1 ? node : node.parentElement;
  while (el) {
    if (el.dataset && el.dataset.noI18n !== undefined) return true;
    el = el.parentElement;
  }
  return false;
}

function translateTextNode(node) {
  if (!node || node.nodeType !== 3) return;
  if (!node.nodeValue || !/\S/.test(node.nodeValue)) return;
  if (isSkipped(node)) return;
  const original = i18nTextOriginals.has(node) ? i18nTextOriginals.get(node) : node.nodeValue;
  if (i18nLang !== "en") {
    if (i18nTextOriginals.has(node)) {
      node.nodeValue = i18nTextOriginals.get(node);
      i18nTextOriginals.delete(node);
    }
    return;
  }
  const key = i18nNormalize(original);
  const translated = I18N_MAP.get(key);
  if (!translated) return;
  if (!i18nTextOriginals.has(node)) i18nTextOriginals.set(node, original);
  const leading = /^\s*/.exec(original)[0];
  const trailing = /\s*$/.exec(original)[0];
  node.nodeValue = leading + translated + trailing;
}

function translateAttributes(el) {
  if (!el || el.nodeType !== 1) return;
  let store = i18nAttrOriginals.get(el);
  I18N_ATTRS.forEach((name) => {
    if (!el.hasAttribute || !el.hasAttribute(name)) return;
    if (i18nLang !== "en") {
      if (store && store[name] !== undefined) {
        el.setAttribute(name, store[name]);
        delete store[name];
      }
      return;
    }
    const value = el.getAttribute(name);
    if (!value || !/\S/.test(value)) return;
    const translated = I18N_MAP.get(i18nNormalize(value));
    if (!translated) return;
    if (!store) {
      store = {};
      i18nAttrOriginals.set(el, store);
    }
    if (store[name] === undefined) store[name] = value;
    if (value !== translated) el.setAttribute(name, translated);
  });
}

function translateSubtree(root) {
  if (!root) return;
  if (root.nodeType === 3) {
    translateTextNode(root);
    return;
  }
  if (root.nodeType !== 1 && root.nodeType !== 9 && root.nodeType !== 11) return;
  if (root.nodeType === 1) {
    if (I18N_SKIP.has(root.tagName)) return;
    if (root.dataset && root.dataset.noI18n !== undefined) return;
    translateAttributes(root);
  }
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
    acceptNode(node) {
      const parent = node.parentElement;
      if (!parent || I18N_SKIP.has(parent.tagName)) return NodeFilter.FILTER_REJECT;
      return NodeFilter.FILTER_ACCEPT;
    },
  });
  const nodes = [];
  while (walker.nextNode()) nodes.push(walker.currentNode);
  nodes.forEach(translateTextNode);
  if (root.querySelectorAll) {
    root.querySelectorAll(I18N_ATTRS.map((a) => `[${a}]`).join(",")).forEach(translateAttributes);
  }
}

function startObserver() {
  if (i18nObserver || typeof MutationObserver === "undefined") return;
  i18nObserver = new MutationObserver((mutations) => {
    if (i18nLang !== "en") return;
    mutations.forEach((mutation) => {
      if (mutation.type === "characterData") {
        translateTextNode(mutation.target);
        return;
      }
      mutation.addedNodes.forEach((node) => translateSubtree(node));
    });
  });
  i18nObserver.observe(document.body, { childList: true, subtree: true });
}

function stopObserver() {
  if (!i18nObserver) return;
  i18nObserver.disconnect();
  i18nObserver = null;
}

function setLanguage(code, options = {}) {
  const next = I18N_LANGS[code] ? code : "fa";
  const meta = I18N_LANGS[next];
  i18nLang = next;
  const root = document.documentElement;
  root.setAttribute("lang", next);
  root.setAttribute("dir", meta.dir);
  document.body.classList.toggle("lang-en", next === "en");
  localStorage.setItem("ks.language", next);

  if (next === "en") {
    translateSubtree(document.body);
    startObserver();
  } else {
    stopObserver();
    translateSubtree(document.body);
  }

  if (options.silent !== true) {
    window.dispatchEvent(new CustomEvent("ks:language", { detail: { language: next } }));
  }
  return next;
}

function initLanguage() {
  let stored = "fa";
  try {
    stored = localStorage.getItem("ks.language") || "fa";
  } catch {
    stored = "fa";
  }
  setLanguage(I18N_LANGS[stored] ? stored : "fa", { silent: true });
}

if (typeof window !== "undefined") {
  window.i18n = {
    t,
    setLanguage,
    currentLanguage,
    currentLocale,
    initLanguage,
    languages: I18N_LANGS,
  };
  window.t = t;
  if (document.body) initLanguage();
  else document.addEventListener("DOMContentLoaded", initLanguage);
}

if (typeof module !== "undefined" && module.exports) {
  module.exports = { I18N_EN, I18N_MAP, i18nNormalize };
}
