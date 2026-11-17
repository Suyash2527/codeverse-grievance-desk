/**
 * Site-wide Marathi, Hindi and English.
 *
 * Deliberately a plain dictionary plus React context rather than an i18n
 * library: the string count is small, the app ships no runtime dependency it
 * does not need, and a missing key falls back to English rather than throwing
 * or rendering a bare key at a citizen.
 *
 * What is NOT translated here, and why: policy reasons, rule explanations and
 * AI rationales arrive from the backend already written in English. Those are
 * records of a decision, not interface copy. The rule *labels* below are the
 * part an officer scans, so those are translated.
 */

export const LANGUAGES = [
  { code: "mr", label: "मराठी", english: "Marathi" },
  { code: "hi", label: "हिंदी", english: "Hindi" },
  { code: "en", label: "English", english: "English" },
] as const;

export type Lang = (typeof LANGUAGES)[number]["code"];

export const DEFAULT_LANG: Lang = "en";

type Dict = Record<string, string>;

const en: Dict = {
  // chrome
  "app.name": "Grievance Desk",
  "app.subtitle": "Nanded district · demo",
  "nav.queue": "Officer queue",
  "nav.file": "File a grievance",
  "nav.track": "Track",
  "nav.rules": "Safety rules",
  "nav.queue.short": "Queue",
  "nav.file.short": "File",
  "nav.track.short": "Track",
  "nav.rules.short": "Rules",
  "nav.language": "Language",
  "footer.notice":
    "Synthetic demonstration data. Not official government records. All contact details are non-operational placeholders and no message is delivered to a real address.",
  "api.offline":
    "Cannot reach the service. Check that the backend is running.",
  "action.retry": "Retry",
  "action.copy": "Copy",
  "action.copied": "Copied",

  // officer queue
  "home.title": "Grievances, read and routed in the open.",
  "home.lead":
    "Write or speak in Marathi, Hindi or English. Agents draft the complaint, retrieve comparable cases and apply the district's own policy table. Every decision carries the rule that produced it, the evidence it was given, and the confidence behind it.",
  "home.refuses": "What it refuses to do",
  "home.proved": "see it proved",
  "home.flowEyebrow": "How a complaint moves",
  "home.flowTitle": "Five agents, one decision, every step recorded",
  "home.flowLead":
    "The pipeline is linear on purpose. One place decides whether a case may be resolved automatically, and that decision is enforced again at the moment anything is written.",
  "hot.eyebrow": "District analytics",
  "hot.title": "Taluka hotspots",
  "hot.lead":
    "Where grievances concentrate, and where the district misses its own deadlines. Aggregated to taluka only — never to a street, and never to a person.",
  "hot.measure.volume": "Case volume",
  "hot.measure.breach": "Deadline failure",
  "hot.caption.volume":
    "Total grievances recorded per taluka. Shows where the district hears the most.",
  "hot.caption.breach":
    "Share of closed cases that exceeded their configured SLA. Shows where the district is slowest.",
  "hot.talukas": "Talukas",
  "hot.pastSla": "Closed late",
  "hot.openNow": "Open now",
  "hot.recorded": "Recorded cases",
  "hot.overdue": "Past deadline",
  "hot.sensitive": "Sensitive cases",
  "hot.mostReported": "Most reported",
  "hot.table": "The same figures as a table",
  "hot.col.taluka": "Taluka",
  "hot.notMap":
    "Markers sit on taluka centroids resolved from OpenStreetMap, not on administrative boundaries, because the supplied dataset carries no geometry of its own.",
  "hot.tapDetail": "Tap a taluka for detail",
  "hot.view.map": "Map",
  "hot.view.list": "Ranked list",
  "hot.map.title": "Where cases are coming from",
  "hot.map.area": "Circle area is proportional to the count",
  "hot.map.missing": "Not shown, no coordinates resolved",
  "hot.map.scale": "low to high",
  "hot.map.caveat":
    "A heat map interpolates between points, and these are 16 taluka centroids rather than a continuous survey. The warm areas show where recorded cases cluster; the markers carry the exact figures.",
  "queue.eyebrow": "Officer console",
  "queue.title": "Grievance queue",
  "queue.lead":
    "Ordered by priority, then by how little time is left. Priority is composed from severity, urgency and affected population — never from how many times something was reported.",
  "queue.count.review": "Needs review",
  "queue.count.sensitive": "Sensitive",
  "queue.count.overdue": "Past deadline",
  "queue.filter.all": "All cases",
  "queue.filter.review": "Awaiting review",
  "queue.filter.sensitive": "Sensitive",
  "queue.filter.overdue": "Past deadline",
  "queue.hotspots": "Taluka hotspots",
  "queue.refresh": "Refresh",
  "queue.updated": "Updated",
  "queue.empty.title": "No cases match.",
  "queue.empty.body": "Run a seed scenario to populate the queue.",
  "queue.reports": "reports",
  "queue.reopened": "reopened",

  // status vocabulary
  "status.sensitive": "Sensitive · human only",
  "status.review": "Needs review",
  "status.auto": "Auto-resolved",
  "status.identityWithheld": "Identity withheld",
  "status.notProvided": "Not provided",
  "status.left": "left",
  "status.overdue": "overdue",
  "label.confidence": "Confidence",
  "priority.CRITICAL": "Critical",
  "priority.HIGH": "High",
  "priority.MEDIUM": "Medium",
  "priority.LOW": "Low",
  "risk.BREACH_LIKELY": "Breach likely",
  "risk.AT_RISK": "At risk",
  "risk.OVERDUE": "Overdue",
  "risk.ON_TRACK": "On track",
  "risk.INSUFFICIENT_HISTORY": "Not enough history",
  "label.unrouted": "unrouted",
  "label.locationUnknown": "location unknown",

  // rule labels
  "rule.sensitive": "Sensitive — human review required",
  "rule.noReject": "Automated rejection refused",
  "rule.belowThreshold": "Below confidence threshold",
  "rule.noAuto": "Category forbids automated resolution",
  "rule.allowed": "Automation permitted",
  "rule.undetermined": "Category undetermined",
  "rule.notInMaster": "Category not in master",
  "rule.precaution": "Held — evidence suggests this may be sensitive",
  "rule.none": "No decision recorded",

  // compliance
  "rules.eyebrow": "Safety contract",
  "rules.title": "The rules this system will not break",
  "rules.lead":
    "Each rule below was just tested against the running policy module and the category table loaded right now. These are not screenshots of a test run — press the button and they execute again.",
  "rules.run": "Run the checks again",
  "rules.running": "Running…",
  "rules.enforced": "enforced",
  "rules.failing": "FAILING",
  "rules.lastRun": "last run",
  "rules.attempted": "Attempted",
  "rules.result": "Result",
  "rules.enforcedBy": "Enforced by",
  "rules.depth": "defence in depth",

  // track
  "track.title": "Track a grievance",
  "track.lead": "Enter the reference number you were given when you filed.",
  "track.check": "Check",
  "track.resolvedQ": "Is this resolved?",
  "track.resolvedBody":
    "If the problem is not actually fixed, say so. Disputing a resolution reopens the case and returns it to an officer.",
  "track.yes": "Yes, this is resolved",
  "track.no": "No, reopen my case",
  "track.timeline": "What has happened so far",
  "track.recorded": "What we recorded",
  "track.department": "Department",
  "track.priority": "Priority",
  "track.due": "Due by",
  "track.reopened": "Reopened",
  "track.new": "File a new grievance",
  "track.placeholder": "Tell us what happened…",
};

const hi: Dict = {
  "app.name": "शिकायत डेस्क",
  "app.subtitle": "नांदेड जिला · डेमो",
  "nav.queue": "अधिकारी सूची",
  "nav.file": "शिकायत दर्ज करें",
  "nav.track": "ट्रैक करें",
  "nav.rules": "सुरक्षा नियम",
  "nav.queue.short": "सूची",
  "nav.file.short": "दर्ज",
  "nav.track.short": "ट्रैक",
  "nav.rules.short": "नियम",
  "nav.language": "भाषा",
  "footer.notice":
    "यह कृत्रिम प्रदर्शन डेटा है। ये सरकारी अभिलेख नहीं हैं। सभी संपर्क विवरण निष्क्रिय प्लेसहोल्डर हैं और कोई संदेश किसी वास्तविक पते पर नहीं भेजा जाता।",
  "api.offline": "सेवा से संपर्क नहीं हो पा रहा। जाँचें कि बैकएंड चल रहा है।",
  "action.retry": "पुनः प्रयास करें",
  "action.copy": "कॉपी करें",
  "action.copied": "कॉपी हो गया",

  "home.title": "शिकायतें, खुले तौर पर पढ़ी और भेजी जाती हैं।",
  "home.lead":
    "मराठी, हिंदी या अंग्रेज़ी में लिखिए या बोलिए। एजेंट शिकायत का मसौदा बनाते हैं, मिलती-जुलती पुरानी शिकायतें खोजते हैं और ज़िले की अपनी नीति तालिका लागू करते हैं। हर निर्णय के साथ वह नियम, वह साक्ष्य और वह विश्वास स्तर दर्ज रहता है जिससे वह बना।",
  "home.refuses": "यह प्रणाली क्या नहीं करेगी",
  "home.proved": "प्रमाण देखें",
  "home.flowEyebrow": "शिकायत कैसे आगे बढ़ती है",
  "home.flowTitle": "पाँच एजेंट, एक निर्णय, हर चरण दर्ज",
  "home.flowLead":
    "यह क्रम जानबूझकर सीधा रखा गया है। केवल एक ही जगह तय करती है कि मामला स्वतः निपट सकता है या नहीं, और वही निर्णय लिखते समय दोबारा जाँचा जाता है।",
  "hot.eyebrow": "ज़िला विश्लेषण",
  "hot.title": "तालुका हॉटस्पॉट",
  "hot.lead":
    "शिकायतें कहाँ केंद्रित हैं, और ज़िला कहाँ अपनी ही समय-सीमा चूकता है। केवल तालुका स्तर तक — न किसी गली तक, न किसी व्यक्ति तक।",
  "hot.measure.volume": "शिकायतों की संख्या",
  "hot.measure.breach": "समय-सीमा चूक",
  "hot.caption.volume":
    "प्रति तालुका दर्ज कुल शिकायतें। दिखाता है कि ज़िला सबसे अधिक कहाँ से सुनता है।",
  "hot.caption.breach":
    "बंद मामलों में से कितने निर्धारित समय-सीमा से आगे गए। दिखाता है कि ज़िला कहाँ सबसे धीमा है।",
  "hot.talukas": "तालुके",
  "hot.pastSla": "देर से बंद",
  "hot.openNow": "अभी खुले",
  "hot.recorded": "दर्ज मामले",
  "hot.overdue": "समय-सीमा पार",
  "hot.sensitive": "संवेदनशील मामले",
  "hot.mostReported": "सर्वाधिक दर्ज",
  "hot.table": "वही आँकड़े तालिका में",
  "hot.col.taluka": "तालुका",
  "hot.notMap":
    "चिह्न OpenStreetMap से प्राप्त तालुका केंद्रबिंदुओं पर हैं, प्रशासनिक सीमाओं पर नहीं, क्योंकि दिए गए डेटा में कोई भू-आकृति नहीं है।",
  "hot.tapDetail": "विवरण हेतु तालुका चुनें",
  "hot.view.map": "नक्शा",
  "hot.view.list": "क्रम सूची",
  "hot.map.title": "शिकायतें कहाँ से आ रही हैं",
  "hot.map.area": "वृत्त का क्षेत्रफल संख्या के अनुपात में है",
  "hot.map.missing": "नहीं दिखाया गया, निर्देशांक नहीं मिले",
  "hot.map.scale": "कम से अधिक",
  "hot.map.caveat":
    "हीट मैप बिंदुओं के बीच अनुमान लगाता है, और ये 16 तालुका केंद्रबिंदु हैं, कोई सतत सर्वेक्षण नहीं। गर्म क्षेत्र दिखाते हैं कि दर्ज शिकायतें कहाँ केंद्रित हैं; सटीक आँकड़े चिह्नों में हैं।",
  "queue.eyebrow": "अधिकारी कक्ष",
  "queue.title": "शिकायत सूची",
  "queue.lead":
    "प्राथमिकता के क्रम में, फिर शेष समय के अनुसार। प्राथमिकता गंभीरता, तात्कालिकता और प्रभावित जनसंख्या से बनती है — कभी भी शिकायतों की संख्या से नहीं।",
  "queue.count.review": "समीक्षा आवश्यक",
  "queue.count.sensitive": "संवेदनशील",
  "queue.count.overdue": "समय-सीमा पार",
  "queue.filter.all": "सभी मामले",
  "queue.filter.review": "समीक्षा लंबित",
  "queue.filter.sensitive": "संवेदनशील",
  "queue.filter.overdue": "समय-सीमा पार",
  "queue.hotspots": "तालुका हॉटस्पॉट",
  "queue.refresh": "ताज़ा करें",
  "queue.updated": "अद्यतन",
  "queue.empty.title": "कोई मामला नहीं मिला।",
  "queue.empty.body": "सूची भरने के लिए एक डेमो परिदृश्य चलाएँ।",
  "queue.reports": "शिकायतें",
  "queue.reopened": "पुनः खोला गया",

  "status.sensitive": "संवेदनशील · केवल मानवीय",
  "status.review": "समीक्षा आवश्यक",
  "status.auto": "स्वतः निपटाया गया",
  "status.identityWithheld": "पहचान गोपनीय",
  "status.notProvided": "नहीं दिया गया",
  "status.left": "शेष",
  "status.overdue": "विलंबित",
  "label.confidence": "विश्वास स्तर",
  "priority.CRITICAL": "अति गंभीर",
  "priority.HIGH": "उच्च",
  "priority.MEDIUM": "मध्यम",
  "priority.LOW": "निम्न",
  "risk.BREACH_LIKELY": "समय-सीमा चूकने की संभावना",
  "risk.AT_RISK": "जोखिम में",
  "risk.OVERDUE": "विलंबित",
  "risk.ON_TRACK": "समय पर",
  "risk.INSUFFICIENT_HISTORY": "पर्याप्त इतिहास नहीं",
  "label.unrouted": "अनिर्दिष्ट",
  "label.locationUnknown": "स्थान अज्ञात",

  "rule.sensitive": "संवेदनशील — मानवीय समीक्षा अनिवार्य",
  "rule.noReject": "स्वचालित अस्वीकृति रोकी गई",
  "rule.belowThreshold": "विश्वास स्तर सीमा से कम",
  "rule.noAuto": "इस श्रेणी में स्वचालित निपटान वर्जित",
  "rule.allowed": "स्वचालन की अनुमति",
  "rule.undetermined": "श्रेणी निर्धारित नहीं",
  "rule.notInMaster": "श्रेणी मास्टर सूची में नहीं",
  "rule.precaution": "रोका गया — साक्ष्य संकेत देते हैं कि यह संवेदनशील हो सकता है",
  "rule.none": "कोई निर्णय दर्ज नहीं",

  "rules.eyebrow": "सुरक्षा अनुबंध",
  "rules.title": "ये नियम यह प्रणाली कभी नहीं तोड़ेगी",
  "rules.lead":
    "नीचे दिया गया हर नियम अभी चल रहे नीति मॉड्यूल और वर्तमान श्रेणी तालिका पर परखा गया है। ये किसी पुराने परीक्षण के चित्र नहीं हैं — बटन दबाइए और ये फिर से चलेंगे।",
  "rules.run": "जाँच फिर से चलाएँ",
  "rules.running": "चल रहा है…",
  "rules.enforced": "लागू",
  "rules.failing": "विफल",
  "rules.lastRun": "पिछली जाँच",
  "rules.attempted": "प्रयास",
  "rules.result": "परिणाम",
  "rules.enforcedBy": "किसके द्वारा लागू",
  "rules.depth": "अतिरिक्त सुरक्षा",

  "track.title": "शिकायत ट्रैक करें",
  "track.lead": "दर्ज करते समय मिला संदर्भ क्रमांक डालिए।",
  "track.check": "देखें",
  "track.resolvedQ": "क्या यह हल हो गया?",
  "track.resolvedBody":
    "यदि समस्या वास्तव में ठीक नहीं हुई है तो बताइए। आपत्ति दर्ज करने पर मामला फिर से खुलेगा और अधिकारी के पास जाएगा।",
  "track.yes": "हाँ, यह हल हो गया",
  "track.no": "नहीं, मेरा मामला फिर खोलें",
  "track.timeline": "अब तक क्या हुआ",
  "track.recorded": "हमने जो दर्ज किया",
  "track.department": "विभाग",
  "track.priority": "प्राथमिकता",
  "track.due": "नियत तिथि",
  "track.reopened": "पुनः खोला गया",
  "track.new": "नई शिकायत दर्ज करें",
  "track.placeholder": "बताइए क्या हुआ…",
};

const mr: Dict = {
  "app.name": "तक्रार कक्ष",
  "app.subtitle": "नांदेड जिल्हा · डेमो",
  "nav.queue": "अधिकारी रांग",
  "nav.file": "तक्रार नोंदवा",
  "nav.track": "मागोवा",
  "nav.rules": "सुरक्षा नियम",
  "nav.queue.short": "रांग",
  "nav.file.short": "नोंद",
  "nav.track.short": "मागोवा",
  "nav.rules.short": "नियम",
  "nav.language": "भाषा",
  "footer.notice":
    "ही कृत्रिम प्रात्यक्षिक माहिती आहे. ही शासकीय नोंद नाही. सर्व संपर्क तपशील निष्क्रिय नमुने आहेत आणि कोणताही संदेश खऱ्या पत्त्यावर पाठवला जात नाही.",
  "api.offline": "सेवेशी संपर्क होत नाही. बॅकएंड सुरू आहे का ते तपासा.",
  "action.retry": "पुन्हा प्रयत्न करा",
  "action.copy": "कॉपी करा",
  "action.copied": "कॉपी झाले",

  "home.title": "तक्रारी, उघडपणे वाचल्या आणि पाठवल्या जातात.",
  "home.lead":
    "मराठी, हिंदी किंवा इंग्रजीत लिहा किंवा बोला. एजंट तक्रारीचा मसुदा तयार करतात, तत्सम जुनी प्रकरणे शोधतात आणि जिल्ह्याचा स्वतःचा धोरण तक्ता लागू करतात. प्रत्येक निर्णयासोबत तो नियम, तो पुरावा आणि ती विश्वास पातळी नोंदवली जाते.",
  "home.refuses": "ही प्रणाली काय करणार नाही",
  "home.proved": "पुरावा पहा",
  "home.flowEyebrow": "तक्रार कशी पुढे जाते",
  "home.flowTitle": "पाच एजंट, एक निर्णय, प्रत्येक पायरी नोंदवलेली",
  "home.flowLead":
    "हा क्रम मुद्दाम सरळ ठेवला आहे. प्रकरण स्वयंचलितपणे निकाली निघू शकते का हे एकाच ठिकाणी ठरते, आणि तोच निर्णय लिहिताना पुन्हा तपासला जातो.",
  "hot.eyebrow": "जिल्हा विश्लेषण",
  "hot.title": "तालुका हॉटस्पॉट",
  "hot.lead":
    "तक्रारी कुठे केंद्रित आहेत, आणि जिल्हा स्वतःची मुदत कुठे चुकवतो. फक्त तालुका पातळीपर्यंत — गल्लीपर्यंत नाही, व्यक्तीपर्यंत तर नाहीच.",
  "hot.measure.volume": "तक्रारींची संख्या",
  "hot.measure.breach": "मुदत चुकण्याचे प्रमाण",
  "hot.caption.volume":
    "प्रत्येक तालुक्यात नोंदलेल्या एकूण तक्रारी. जिल्हा सर्वाधिक कुठून ऐकतो हे दाखवते.",
  "hot.caption.breach":
    "बंद झालेल्या प्रकरणांपैकी किती ठरलेली मुदत ओलांडली. जिल्हा कुठे सर्वात संथ आहे हे दाखवते.",
  "hot.talukas": "तालुके",
  "hot.pastSla": "उशिरा बंद",
  "hot.openNow": "सध्या सुरू",
  "hot.recorded": "नोंदलेली प्रकरणे",
  "hot.overdue": "मुदत संपलेली",
  "hot.sensitive": "संवेदनशील प्रकरणे",
  "hot.mostReported": "सर्वाधिक नोंदलेले",
  "hot.table": "तेच आकडे तक्त्यात",
  "hot.col.taluka": "तालुका",
  "hot.notMap":
    "खुणा OpenStreetMap वरून मिळालेल्या तालुका मध्यबिंदूंवर आहेत, प्रशासकीय सीमांवर नाहीत, कारण दिलेल्या माहितीत कोणतीही भूरचना नाही.",
  "hot.tapDetail": "तपशीलासाठी तालुका निवडा",
  "hot.view.map": "नकाशा",
  "hot.view.list": "क्रमवारी यादी",
  "hot.map.title": "तक्रारी कुठून येत आहेत",
  "hot.map.area": "वर्तुळाचे क्षेत्रफळ संख्येच्या प्रमाणात आहे",
  "hot.map.missing": "दाखवले नाही, निर्देशांक मिळाले नाहीत",
  "hot.map.scale": "कमी ते जास्त",
  "hot.map.caveat":
    "हीट मॅप बिंदूंमधील अंदाज बांधतो, आणि हे १६ तालुका मध्यबिंदू आहेत, सलग सर्वेक्षण नाही. उष्ण भाग नोंदलेल्या तक्रारी कुठे केंद्रित आहेत हे दाखवतात; नेमके आकडे खुणांमध्ये आहेत.",
  "queue.eyebrow": "अधिकारी कक्ष",
  "queue.title": "तक्रार रांग",
  "queue.lead":
    "प्राधान्यानुसार, नंतर उरलेल्या वेळेनुसार क्रम. प्राधान्य तीव्रता, निकड आणि बाधित लोकसंख्येतून ठरते — तक्रारींच्या संख्येवरून कधीही नाही.",
  "queue.count.review": "पुनरावलोकन आवश्यक",
  "queue.count.sensitive": "संवेदनशील",
  "queue.count.overdue": "मुदत संपलेली",
  "queue.filter.all": "सर्व प्रकरणे",
  "queue.filter.review": "पुनरावलोकन बाकी",
  "queue.filter.sensitive": "संवेदनशील",
  "queue.filter.overdue": "मुदत संपलेली",
  "queue.hotspots": "तालुका हॉटस्पॉट",
  "queue.refresh": "रिफ्रेश",
  "queue.updated": "अद्ययावत",
  "queue.empty.title": "कोणतेही प्रकरण आढळले नाही.",
  "queue.empty.body": "रांग भरण्यासाठी एक प्रात्यक्षिक परिस्थिती चालवा.",
  "queue.reports": "तक्रारी",
  "queue.reopened": "पुन्हा उघडले",

  "status.sensitive": "संवेदनशील · फक्त मानवी",
  "status.review": "पुनरावलोकन आवश्यक",
  "status.auto": "स्वयंचलित निकाल",
  "status.identityWithheld": "ओळख गोपनीय",
  "status.notProvided": "दिलेले नाही",
  "status.left": "शिल्लक",
  "status.overdue": "मुदत उलटली",
  "label.confidence": "विश्वास पातळी",
  "priority.CRITICAL": "अत्यंत गंभीर",
  "priority.HIGH": "उच्च",
  "priority.MEDIUM": "मध्यम",
  "priority.LOW": "कमी",
  "risk.BREACH_LIKELY": "मुदत चुकण्याची शक्यता",
  "risk.AT_RISK": "धोक्यात",
  "risk.OVERDUE": "मुदत उलटली",
  "risk.ON_TRACK": "वेळेत",
  "risk.INSUFFICIENT_HISTORY": "पुरेसा इतिहास नाही",
  "label.unrouted": "अनिश्चित",
  "label.locationUnknown": "ठिकाण अज्ञात",

  "rule.sensitive": "संवेदनशील — मानवी पुनरावलोकन अनिवार्य",
  "rule.noReject": "स्वयंचलित नकार रोखला",
  "rule.belowThreshold": "विश्वास पातळी मर्यादेपेक्षा कमी",
  "rule.noAuto": "या श्रेणीत स्वयंचलित निकाल निषिद्ध",
  "rule.allowed": "स्वयंचलनास परवानगी",
  "rule.undetermined": "श्रेणी निश्चित नाही",
  "rule.notInMaster": "श्रेणी मुख्य यादीत नाही",
  "rule.precaution": "थांबवले — पुरावे सूचित करतात की हे संवेदनशील असू शकते",
  "rule.none": "कोणताही निर्णय नोंदवलेला नाही",

  "rules.eyebrow": "सुरक्षा करार",
  "rules.title": "ही प्रणाली जे नियम कधीच मोडणार नाही",
  "rules.lead":
    "खालील प्रत्येक नियम आत्ताच चालू असलेल्या धोरण मॉड्यूलवर आणि सध्याच्या श्रेणी तक्त्यावर तपासला गेला आहे. ही जुन्या चाचणीची चित्रे नाहीत — बटण दाबा आणि ते पुन्हा चालतील.",
  "rules.run": "तपासणी पुन्हा चालवा",
  "rules.running": "चालू आहे…",
  "rules.enforced": "अंमलात",
  "rules.failing": "अयशस्वी",
  "rules.lastRun": "शेवटची तपासणी",
  "rules.attempted": "प्रयत्न",
  "rules.result": "निकाल",
  "rules.enforcedBy": "कशाद्वारे अंमलात",
  "rules.depth": "अतिरिक्त सुरक्षा",

  "track.title": "तक्रारीचा मागोवा घ्या",
  "track.lead": "नोंदवताना मिळालेला संदर्भ क्रमांक टाका.",
  "track.check": "तपासा",
  "track.resolvedQ": "हे सुटले आहे का?",
  "track.resolvedBody":
    "समस्या खरोखर सुटली नसेल तर सांगा. आक्षेप नोंदवल्यास प्रकरण पुन्हा उघडेल आणि अधिकाऱ्याकडे जाईल.",
  "track.yes": "होय, हे सुटले आहे",
  "track.no": "नाही, माझे प्रकरण पुन्हा उघडा",
  "track.timeline": "आतापर्यंत काय घडले",
  "track.recorded": "आम्ही जे नोंदवले",
  "track.department": "विभाग",
  "track.priority": "प्राधान्य",
  "track.due": "मुदत",
  "track.reopened": "पुन्हा उघडले",
  "track.new": "नवीन तक्रार नोंदवा",
  "track.placeholder": "काय घडले ते सांगा…",
};

export const DICTIONARIES: Record<Lang, Dict> = { en, hi, mr };

/** English is the fallback: a missing key shows real words, never a key. */
export function translate(lang: Lang, key: string): string {
  return DICTIONARIES[lang]?.[key] ?? en[key] ?? key;
}

/** Backend rule constants mapped to a translated label. */
export const RULE_KEYS: Record<string, string> = {
  RULE_1_SENSITIVE_NEVER_AUTO_CLOSED: "rule.sensitive",
  RULE_2_AI_NEVER_REJECTS_OR_RULES_ON_LIABILITY: "rule.noReject",
  RULE_5_DECISION_BELOW_CONFIDENCE_THRESHOLD: "rule.belowThreshold",
  CATEGORY_AUTO_RESOLUTION_NOT_ALLOWED: "rule.noAuto",
  CATEGORY_AUTO_RESOLUTION_ALLOWED_AND_CONFIDENT: "rule.allowed",
  CATEGORY_UNDETERMINED_REQUIRES_HUMAN_REVIEW: "rule.undetermined",
  CATEGORY_NOT_IN_MASTER_REQUIRES_HUMAN_REVIEW: "rule.notInMaster",
  PRECAUTIONARY_SENSITIVE_NEIGHBOUR_HUMAN_REVIEW: "rule.precaution",
};
