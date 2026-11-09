const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));

let currentUser = null;
let supabaseClient = null;
let supabaseAccessToken = null;
const API_BASE_URL = String(window.LOSTLINK_API_BASE_URL || '').replace(/\/$/, '');

function createSupabaseRestAuthClient(supabaseUrl, anonKey) {
  const base = String(supabaseUrl || "").replace(/\\/$/, "");
  const storageKey = "lostlink:supabase-office-session";
  let session = null;
  try {
    const stored = sessionStorage.getItem(storageKey);
    session = stored ? JSON.parse(stored) : null;
  } catch (_) { session = null; }

  function persist(next) {
    session = next || null;
    try {
      if (session) sessionStorage.setItem(storageKey, JSON.stringify(session));
      else sessionStorage.removeItem(storageKey);
    } catch (_) {}
  }
  async function authRequest(path, body, accessToken) {
    const headers = {"apikey": anonKey, "Content-Type": "application/json"};
    if (accessToken) headers.Authorization = "Bearer " + accessToken;
    const response = await fetch(base + path, {
      method: "POST", headers, body: JSON.stringify(body || {}), credentials: "omit"
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      const error = new Error(payload.msg || payload.message || payload.error_description || payload.error || "Supabase authentication failed.");
      error.status = response.status;
      throw error;
    }
    return payload;
  }
  async function refreshIfNeeded() {
    if (!session) return null;
    const expiresAt = Number(session.expires_at || 0);
    if (!expiresAt || expiresAt * 1000 > Date.now() + 60000) return session;
    if (!session.refresh_token) { persist(null); return null; }
    try {
      const refreshed = await authRequest("/auth/v1/token?grant_type=refresh_token", {
        refresh_token: session.refresh_token
      });
      persist({
        ...refreshed,
        expires_at: refreshed.expires_at || Math.floor(Date.now() / 1000) + Number(refreshed.expires_in || 3600)
      });
      return session;
    } catch (_) {
      persist(null);
      return null;
    }
  }
  return {
    auth: {
      async getSession() {
        const current = await refreshIfNeeded();
        return {data: {session: current}, error: null};
      },
      async signInWithPassword(credentials) {
        try {
          const signedIn = await authRequest("/auth/v1/token?grant_type=password", {
            email: String(credentials.email || "").trim().toLowerCase(),
            password: String(credentials.password || "")
          });
          persist({
            ...signedIn,
            expires_at: signedIn.expires_at || Math.floor(Date.now() / 1000) + Number(signedIn.expires_in || 3600)
          });
          return {data: {session, user: session.user || null}, error: null};
        } catch (error) {
          return {data: {session: null, user: null}, error};
        }
      },
      async signOut() {
        try {
          const current = await refreshIfNeeded();
          if (current && current.access_token) {
            await authRequest("/auth/v1/logout", {}, current.access_token);
          }
          persist(null);
          return {error: null};
        } catch (error) {
          return {error};
        }
      }
    }
  };
}

let appConfig = null;
let selectedClaimReport = null;
let selectedLostReportForMatchId = null;
let lostReportOptionsRequest = 0;
let reportSubmitting = false;
let activeReportKind = "lost";
let claimSubmitting = false;
let selectedEvidenceClaimId = null;
let selectedStorageReportId = null;
let selectedHandoverClaimId = null;
let selectedHandoverRollNumber = null;
let selectedDecisionClaimId = null;
let selectedDecisionAction = null;
let claimDecisionSubmitting = false;
let selectedCloseReportId = null;
let selectedCloseReportType = null;

const CATEGORY_ICONS = {
  stationery: "▤", clothing: "◈", bags_wallets: "▣", accessories: "◇",
  electronics: "⌁", identity_documents: "▧", keys_access: "⌘",
  cash_jewellery: "✧", sports_instruments: "◎", other: "◌"
};
const STATUS_LABELS = {
  open: "Open", awaiting_intake: "Awaiting office intake", available: "Available at office",
  claim_approved: "Awaiting handover", pending: "Under review", disputed: "Disputed · review required",
  needs_more_evidence: "More evidence requested", approved_for_collection: "Ready for handover",
  rejected: "Not approved", returned: "Returned to owner", closed: "Closed", cancelled: "Withdrawn"
};
const escapeHTML = (value) => String(value == null ? "" : value).replace(/[&<>"']/g, (char) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
}[char]));

function explainError(data, fallback) {
  if (!data || !data.detail) return fallback || "Something went wrong.";
  if (Array.isArray(data.detail)) return data.detail.map((x) => { const field = Array.isArray(x.loc) ? x.loc.filter(part => part !== "body").join(" → ") : ""; return (field ? field + ": " : "") + (x.msg || "Invalid value"); }).join(" ");
  return String(data.detail);
}


const usingMockApi = false;
let mockNoticeShown = false;
const PAGE_SIZE = 50;
const pageState = {
  browse: { cursor: null, hasMore: false, loading: false },
  myReports: { cursor: null, hasMore: false, loading: false },
  myClaims: { cursor: null, hasMore: false, loading: false },
  intake: { cursor: null, hasMore: false, loading: false, items: [] },
  inventory: { cursor: null, hasMore: false, loading: false, items: [] },
  officeClaims: { cursor: null, hasMore: false, loading: false, items: [] },
  handovers: { cursor: null, hasMore: false, loading: false, items: [] },
  privacyRequests: { cursor: null, hasMore: false, loading: false, items: [] }
};
let inspectedUser = null;
let notificationPollTimer = null;
let notificationPollInFlight = false;
const MOCK_CATEGORIES = [
 {value:"stationery",label:"Stationery & books"},{value:"clothing",label:"Clothing & everyday items"},
 {value:"bags_wallets",label:"Bags & wallets"},{value:"accessories",label:"Personal accessories"},
 {value:"electronics",label:"Electronics"},{value:"identity_documents",label:"Identity documents & cards"},
 {value:"keys_access",label:"Keys & access cards"},{value:"cash_jewellery",label:"Cash & jewellery"},
 {value:"sports_instruments",label:"Sports equipment & instruments"},{value:"other",label:"Other"}
];
const MOCK_USERS = {
 student:{id:101,email:"student@lostlink.local",display_name:"Alex Chen",role:"student"},
 student2:{id:102,email:"student2@lostlink.local",display_name:"Maya Patel",role:"student"},
 office:{id:900,email:"office@lostlink.local",display_name:"Campus Office",role:"office"}
};
const mockStore={seeded:false,session:null,reports:[],claims:[],notifications:[],ledger:[],certificates:[],reportImages:{},evidenceImages:{}};
const mockCopy=value=>JSON.parse(JSON.stringify(value));
const mockTimestamp=daysAgo=>new Date(Date.now()-(daysAgo||0)*86400000).toISOString();
function seedMockStore(){
 if(mockStore.seeded)return; mockStore.seeded=true;
 const base={brand:null,primary_color:null,visible_features:null,occurred_at:mockTimestamp(1),location_block:"Block A",location_floor:"1",location_room:"A-101",location_area:"Library entrance",image_path:null,status:"available",value_band:"medium",sensitivity_level:1,verification_level:2,private_detail:"Staff-only identifying detail reserved for office review.",storage_location:"Lost & Found room · Cabinet A · Shelf 01",created_by:900,created_at:mockTimestamp(1),updated_at:mockTimestamp(1)};
 mockStore.reports=[
 {...base,id:"mock-found-backpack",public_ref:"LL-F-1024",report_type:"found",title:"Navy backpack",description:"Dark blue backpack with two front pockets and a silver zipper pull.",brand:"Wildcraft",primary_color:"Navy blue",visible_features:"Two front pockets; silver zipper pull",category:"bags_wallets",tag_id:"LL-CVR-2026-000101",private_detail:"Tiny stitched mark inside the left strap."},
 {...base,id:"mock-found-earbuds",public_ref:"LL-F-1025",report_type:"found",title:"Wireless earbuds case",description:"Black wireless earbud charging case found beside the library study area.",primary_color:"Black",visible_features:"Small white sticker on the back edge",category:"accessories",location_room:"",location_area:"Library study area",tag_id:"LL-CVR-2026-000102",private_detail:"Small white sticker on the back edge."},
 {...base,id:"mock-found-bottle",public_ref:"LL-F-1026",report_type:"found",title:"Steel water bottle",description:"Silver insulated bottle with a black cap and a scratch near the base.",primary_color:"Silver",visible_features:"Black cap; scratch near base",category:"accessories",location_block:"Block B",location_floor:"Ground",location_room:"",location_area:"Cafeteria",tag_id:"LL-CVR-2026-000103",private_detail:"Small dent underneath the base."},
 {...base,id:"mock-awaiting-umbrella",public_ref:"LL-F-1027",report_type:"found",title:"Grey folding umbrella",description:"Compact grey folding umbrella with a curved handle.",primary_color:"Grey",visible_features:"Curved handle",category:"clothing",status:"awaiting_intake",created_by:102,tag_id:null,storage_location:null,private_detail:null,location_block:"Block B",location_floor:"Ground",location_room:"",location_area:"Cafeteria entrance"},
 {...base,id:"mock-lost-backpack",public_ref:"LL-L-1024",report_type:"lost",title:"Dark blue backpack",description:"I lost a dark blue backpack with two front pockets around the library.",primary_color:"Navy blue",visible_features:"Two front pockets",category:"bags_wallets",status:"open",created_by:101,tag_id:null,storage_location:null,private_detail:null,location_area:"Library",location_room:"",verification_level:null},
 {...base,id:"mock-lost-bottle",public_ref:"LL-L-1025",report_type:"lost",title:"Silver insulated bottle",description:"A steel water bottle with black lid, last seen by cafeteria.",primary_color:"Silver",visible_features:"Black cap",category:"accessories",status:"open",created_by:102,tag_id:null,storage_location:null,private_detail:null,location_block:"Block B",location_floor:"Ground",location_room:"",location_area:"Cafeteria",verification_level:null}
 ];
 mockStore.claims=[{id:"mock-claim-backpack",report_id:"mock-found-backpack",lost_report_id:"mock-lost-backpack",claimant_id:101,claimant_name:"Alex Chen",claimant_email:MOCK_USERS.student.email,evidence:"I can identify a stitched mark inside the left strap and have a purchase receipt for the bag.",evidence_types:["distinctive_features","purchase_or_receipt"],status:"pending",appeal_note:null,appeal_count:0,reviewer_note:null,created_at:mockTimestamp(0),updated_at:mockTimestamp(0),verification_checks:[]}];
 mockStore.notifications=[
 {id:"mock-notice-match",user_id:101,event_key:"mock-match",title:"A possible item match was found",message:"A found backpack may match your open lost report LL-L-1024.",entity_type:"report",entity_id:"mock-lost-backpack",read_at:null,created_at:mockTimestamp(0)},
 {id:"mock-notice-intake",user_id:900,event_key:"mock-intake",title:"Found-item report awaiting intake",message:"A grey folding umbrella is waiting for physical intake.",entity_type:"report",entity_id:"mock-awaiting-umbrella",read_at:null,created_at:mockTimestamp(0)}
 ];
 mockStore.ledger=[
 {user_id:101,points:10,reason:"Found item received and tagged by the campus office",report_id:"mock-found-backpack",created_at:mockTimestamp(4)},
 {user_id:102,points:15,reason:"Verified campus contribution",report_id:"mock-found-bottle",created_at:mockTimestamp(2)}
 ];
 mockStore.certificates=[{id:"mock-cert-finder",user_id:101,tier:"Verified Finder",threshold_points:20,points_at_issue:20,serial:"LL-CERT-DEMO-0001",issued_at:mockTimestamp(2)}];
 mockStore.session=mockCopy(MOCK_USERS.student);
}
function enableMockMode(){
  throw new Error("Client-side mock authentication is disabled. Use the configured LostLink API and office-only demo access.");
}
function mockNotify(userId,title,message,entityType,entityId,eventKey){
 const key=eventKey||("demo:"+title+":"+entityId+":"+Date.now());
 if(mockStore.notifications.some(n=>n.user_id===userId&&n.event_key===key))return;
 mockStore.notifications.unshift({id:"mock-notice-"+Math.random().toString(36).slice(2,10),user_id:userId,event_key:key,title,message,entity_type:entityType||null,entity_id:entityId||null,read_at:null,created_at:mockTimestamp(0)});
}
function mockReadBody(options){
 if(!options||!options.body||options.body instanceof FormData)return options&&options.body instanceof FormData?options.body:{};
 if(typeof options.body==="string"){try{return JSON.parse(options.body);}catch(_){return {};}}
 return options.body;
}
function mockReportView(report,internal){
 const sensitive=["identity_documents","keys_access"].includes(report.category)&&!internal, image=mockStore.reportImages[report.id]||null;
 const result={id:report.id,public_ref:report.public_ref,report_type:report.report_type,title:report.title,description:report.description,
 brand:report.brand,primary_color:report.primary_color,visible_features:report.visible_features,category:report.category,
 category_label:(MOCK_CATEGORIES.find(x=>x.value===report.category)||{}).label||report.category,occurred_at:report.occurred_at,
 location:[report.location_block,report.location_floor?"Floor "+report.location_floor:null,(internal||!sensitive)?report.location_room:null,report.location_area].filter(Boolean).join(" · ")||"Location not specified",
 location_block:report.location_block,location_floor:report.location_floor,location_room:internal?report.location_room:null,location_area:report.location_area,
 image_url:sensitive||!image?null:image,status:report.status,created_at:report.created_at,updated_at:report.updated_at};
 if(internal)Object.assign(result,{tag_id:report.tag_id,private_verification_detail:report.private_detail,value_band:report.value_band||"unknown",sensitivity_level:report.sensitivity_level||1,verification_level:report.verification_level,storage_location:report.tag_id?report.storage_location:null,created_by:report.created_by});
 if(report.report_type==="lost"&&currentUser&&currentUser.id===report.created_by)result.has_active_linked_claim=mockStore.claims.some(c=>c.lost_report_id===report.id&&["pending","disputed","needs_more_evidence","approved_for_collection"].includes(c.status));
 return result;
}
function mockClaimView(claim,internal){
 const report=mockStore.reports.find(r=>r.id===claim.report_id), linked=mockStore.reports.find(r=>r.id===claim.lost_report_id);
 const result={id:claim.id,status:claim.status,evidence_types:claim.evidence_types||[],evidence_image_available:Boolean(mockStore.evidenceImages[claim.id]),created_at:claim.created_at,updated_at:claim.updated_at,appeal_note:claim.appeal_note||null,appeal_count:claim.appeal_count||0,linked_lost_report:linked?{id:linked.id,public_ref:linked.public_ref,title:linked.title,status:linked.status}:null,report:report?mockReportView(report,internal):null};
 if(internal)Object.assign(result,{evidence:claim.evidence,claimant_name:claim.claimant_name,claimant_email:claim.claimant_email,reviewer_note:claim.reviewer_note||null});
 return result;
}
async function mockFileDataUrl(file){
 if(!file||!window.FileReader)return null;
 return await new Promise(resolve=>{const reader=new FileReader();reader.onload=()=>resolve(String(reader.result||""));reader.onerror=()=>resolve(null);reader.readAsDataURL(file);});
}
function mockRequireOffice(){if(!currentUser||currentUser.role!=="office")throw new Error("Office staff access required.");}
function mockCertificateDownload(certificateId){
 const cert=mockStore.certificates.find(c=>c.id===certificateId&&(currentUser.role==="office"||c.user_id===currentUser.id));
 if(!cert){showToast("Certificate not found for this demo account.",true);return;}
 const safe=v=>String(v||"").replace(/[^\x20-\x7E]/g,"?").replace(/([\\()])/g,"\\$1");
 const lines=["LOSTLINK - CERTIFICATE OF RECOGNITION",cert.tier,"Awarded to "+currentUser.display_name,String(cert.points_at_issue)+" verified activity points","Certificate ID: "+cert.serial,"Issued: "+String(cert.issued_at).slice(0,10),"Demo preview - not an official college credential"];
 const stream="BT\n/F1 18 Tf\n60 740 Td\n("+safe(lines[0])+") Tj\n/F1 15 Tf\n0 -54 Td\n("+safe(lines[1])+") Tj\n/F1 11 Tf\n0 -40 Td\n("+safe(lines[2])+") Tj\n0 -26 Td\n("+safe(lines[3])+") Tj\n0 -24 Td\n("+safe(lines[4])+") Tj\n0 -20 Td\n("+safe(lines[5])+") Tj\n0 -42 Td\n("+safe(lines[6])+") Tj\nET";
 const objects=["<< /Type /Catalog /Pages 2 0 R >>","<< /Type /Pages /Kids [3 0 R] /Count 1 >>","<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>","<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>","<< /Length "+stream.length+" >>\nstream\n"+stream+"\nendstream"];
 let pdf="%PDF-1.4\n",offsets=[0];objects.forEach((obj,i)=>{offsets.push(pdf.length);pdf+=(i+1)+" 0 obj\n"+obj+"\nendobj\n";});
 const xref=pdf.length;pdf+="xref\n0 6\n0000000000 65535 f \n";for(let i=1;i<offsets.length;i++)pdf+=String(offsets[i]).padStart(10,"0")+" 00000 n \n";
 pdf+="trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n"+xref+"\n%%EOF";
 const a=document.createElement("a"),url=URL.createObjectURL(new Blob([pdf],{type:"application/pdf"}));a.href=url;a.download="LostLink-"+cert.serial+".pdf";document.body.appendChild(a);a.click();a.remove();window.setTimeout(()=>URL.revokeObjectURL(url),1000);showToast("Demo certificate PDF generated locally.",false);
}
async function mockApi(url,options){
 seedMockStore();const parsed=new URL(url,window.location.href),path=parsed.pathname,method=(options&&options.method||"GET").toUpperCase(),body=mockReadBody(options);
 if(path==="/api/config"&&method==="GET")return {demo_mode:true,points:{verified_intake:10,verified_return:5},certificate_milestones:[{tier:"Verified Finder",threshold:20},{tier:"Campus Helper",threshold:50},{tier:"Community Champion",threshold:100}],categories:mockCopy(MOCK_CATEGORIES),locations:{blocks:["Block A","Block B","Block C","Library","Cafeteria","Other / not sure"],floors:["Ground","1","2","3","Other / not sure"],note:"Interactive local preview"}};
 if(path==="/api/me"&&method==="GET"){mockStore.session=mockStore.session||mockCopy(MOCK_USERS.student);return {user:mockCopy(mockStore.session)};}
 if(path==="/api/login"&&method==="POST"){const email=String(body.email||"").toLowerCase(),user=email.includes("office")?MOCK_USERS.office:email.includes("student2")?MOCK_USERS.student2:MOCK_USERS.student;mockStore.session=mockCopy(user);return {user:mockCopy(user)};}
 if(path==="/api/logout"&&method==="POST"){mockStore.session=null;return {ok:true};}
 if(path==="/api/reports"&&method==="GET"){
  const q=String(parsed.searchParams.get("q")||"").trim().toLowerCase(),mine=parsed.searchParams.get("mine")==="true",internal=currentUser&&currentUser.role==="office";
  const filtered=mockStore.reports.filter(r=>{
   if(!internal&&mine&&r.created_by!==currentUser.id)return false;
   if(!internal&&!mine&&!(r.report_type==="found"&&r.status==="available"))return false;
   for(const [param,field] of [["report_type","report_type"],["category","category"]])if(parsed.searchParams.get(param)&&r[field]!==parsed.searchParams.get(param))return false;
   if(parsed.searchParams.get("block")&&!(r.location_block||"").toLowerCase().includes(parsed.searchParams.get("block").toLowerCase()))return false;
   if(parsed.searchParams.get("room")&&!(r.location_room||"").toLowerCase().includes(parsed.searchParams.get("room").toLowerCase()))return false;
   if(internal&&parsed.searchParams.get("status")){
    const statuses=parsed.searchParams.get("status").split(",").map(x=>x.trim()).filter(Boolean);
    if(!statuses.includes(r.status))return false;
   }
   if(parsed.searchParams.get("date_from")&&String(r.occurred_at||"")<parsed.searchParams.get("date_from"))return false;
   if(parsed.searchParams.get("date_to")&&String(r.occurred_at||"")>parsed.searchParams.get("date_to")+"T23:59:59")return false;
   if(q&&!([r.title,r.description,r.public_ref,r.location_area,r.brand,r.primary_color,r.visible_features,r.location_block,r.location_floor,r.location_room].join(" ").toLowerCase().includes(q)))return false;
   return true;
  }).sort((a,b)=>b.created_at.localeCompare(a.created_at));
  const pageSize=Math.max(1,Math.min(100,Number(parsed.searchParams.get("page_size")||50)));
  const offset=Math.max(0,Number(parsed.searchParams.get("cursor")||0));
  const page=filtered.slice(offset,offset+pageSize),hasMore=offset+pageSize<filtered.length;
  return {reports:page.map(r=>mockReportView(r,Boolean(internal))),next_cursor:hasMore?String(offset+pageSize):null,has_more:hasMore};
 }
 if(path==="/api/reports/category-suggestion"&&method==="POST"){
  const textValue=[body.title,body.description,body.brand,body.primary_color,body.visible_features].filter(Boolean).join(" ").toLowerCase();
  const rules=[["electronics",/phone|mobile|laptop|tablet|charger|camera|cable|power bank/],["identity_documents",/identity card|student id|college id|passport|driving licence|debit card|credit card/],["keys_access",/key|keychain|access card/],["bags_wallets",/backpack|rucksack|handbag|wallet|purse|bag/],["stationery",/notebook|textbook|pen|pencil|calculator|ruler/],["clothing",/shirt|jacket|hoodie|sweater|jeans|shoe|uniform/],["accessories",/watch|glasses|spectacles|earbuds|headphones|bracelet|necklace/],["cash_jewellery",/cash|money|coin|gold|silver|jewellery|jewelry/],["sports_instruments",/football|cricket bat|racket|guitar|violin/]];
  const found=rules.find((rule)=>rule[1].test(textValue));
  const category=found?found[0]:null;
  const label=(MOCK_CATEGORIES.find((item)=>item.value===category)||{}).label||null;
  return {suggestion:category?{status:"suggested",category,label,alternatives:[{category,label,score:1}],engine:"demo_keyword_fallback",requires_confirmation:true}:{status:"uncertain",category:null,alternatives:[],engine:"demo_keyword_fallback",requires_confirmation:true}};
 }
 if(path==="/api/reports"&&method==="POST"){
  if(!currentUser||currentUser.role!=="student")throw new Error("Submit reports from a student account.");
  if(String(body.title||"").trim().length<4||String(body.description||"").trim().length<10)throw new Error("Enter a meaningful item title and description.");
  const report={id:"mock-report-"+Math.random().toString(36).slice(2,10),public_ref:"LL-"+Math.random().toString(36).slice(2,8).toUpperCase(),report_type:body.report_type,title:String(body.title).trim(),description:String(body.description).trim(),brand:body.brand||null,primary_color:body.primary_color||null,visible_features:body.visible_features||null,category:body.category,occurred_at:body.occurred_at||mockTimestamp(0),location_block:body.location_block||"",location_floor:body.location_floor||"",location_room:body.location_room||"",location_area:body.location_area||"",image_path:null,status:body.report_type==="lost"?"open":"awaiting_intake",value_band:"unknown",sensitivity_level:1,verification_level:null,tag_id:null,storage_location:null,private_detail:null,created_by:currentUser.id,created_at:mockTimestamp(0),updated_at:mockTimestamp(0)};
  mockStore.reports.unshift(report);mockNotify(currentUser.id,body.report_type==="lost"?"Lost report submitted":"Found report submitted",body.report_type==="lost"?"Your lost report is saved.":"Your found report is waiting for office intake.","report",report.id,"report-created:"+report.id);
  if(report.report_type==="found")mockNotify(MOCK_USERS.office.id,"Found-item report awaiting intake","A new found-item report is waiting for physical office intake.","report",report.id,"found-report:"+report.id);
  return {report:mockReportView(report,currentUser.role==="office"),message:report.report_type==="lost"?"Lost report submitted.":"Found-item report submitted for office intake."};
 }
 let m=path.match(/^\/api\/reports\/([^/]+)\/(image|matches|intake|storage|close)$/);
 if(m){
  const id=decodeURIComponent(m[1]),action=m[2],report=mockStore.reports.find(r=>r.id===id);if(!report)throw new Error("Report not found.");
  if(action==="image"&&method==="POST"){const file=body instanceof FormData?body.get("file"):null,data=await mockFileDataUrl(file);if(data)mockStore.reportImages[id]=data;report.updated_at=mockTimestamp(0);return {report:mockReportView(report,currentUser.role==="office")};}
  if(action==="matches"&&method==="GET"){
   const candidates=mockStore.reports.filter(r=>r.report_type==="found"&&r.status==="available").map(r=>{
    const terms=(report.title+" "+report.description).toLowerCase().split(/\W+/).filter(x=>x.length>2),hay=(r.title+" "+r.description+" "+(r.primary_color||"")+" "+(r.visible_features||"")).toLowerCase(),overlap=terms.filter(term=>hay.includes(term)).length,score=Math.min(.94,.48+overlap*.055);
    return {report:mockReportView(r,false),score,strength:score>=.72?"strong":score>=.45?"possible":"limited",reasons:["Descriptions contain overlapping item terms.","Category and reported location can help narrow review."]};
   }).sort((a,b)=>b.score-a.score).slice(0,5);return {matches:candidates};
  }
  if(action==="intake"&&method==="POST"){
   mockRequireOffice();if(report.report_type!=="found"||report.status!=="awaiting_intake"||body.confirmed_physical_receipt!==true)throw new Error("Confirm physical receipt for an item awaiting intake.");
   report.storage_location=String(body.storage_location||"").trim();if(report.storage_location.length<4)throw new Error("Enter a specific storage location.");
   report.private_detail=body.private_detail||null;report.value_band=body.value_band||"unknown";report.sensitivity_level=Number(body.sensitivity_level||1);
   const defaults={stationery:1,clothing:1,bags_wallets:2,accessories:2,electronics:3,identity_documents:4,keys_access:4,cash_jewellery:3,sports_instruments:2,other:3};
   report.verification_level=report.sensitivity_level>=3?4:Math.max(defaults[report.category]||3,report.sensitivity_level);
   report.tag_id="LL-CVR-"+new Date().getFullYear()+"-"+String(mockStore.reports.indexOf(report)+101).padStart(6,"0");report.status="available";report.updated_at=mockTimestamp(0);
   mockNotify(MOCK_USERS.office.id,"Intake confirmed","The item was tagged and placed into campus custody.","report",id,"intake:"+id);
   if(report.created_by!==MOCK_USERS.office.id){mockStore.ledger.unshift({user_id:report.created_by,points:10,reason:"Found item received and tagged by the campus office",report_id:id,created_at:mockTimestamp(0)});mockNotify(report.created_by,"Found item received and stored","Your item has been accepted by the campus office.","report",id,"intake-reward:"+id);}
   return {report:mockReportView(report,true),message:"Item received, tagged and stored."};
  }
  if(action==="storage"&&method==="POST"){mockRequireOffice();if(!report.tag_id)throw new Error("Only tagged items in custody can be moved.");report.storage_location=String(body.storage_location||"").trim();report.updated_at=mockTimestamp(0);return {report:mockReportView(report,true),message:"Storage location updated."};}
  if(action==="close"&&method==="POST"){if(!currentUser||currentUser.role!=="student"||report.created_by!==currentUser.id)throw new Error("Report not found.");if(report.report_type==="lost"&&report.status==="open")report.status="closed";else if(report.report_type==="found"&&report.status==="awaiting_intake"&&body.reason==="found_report_withdrawn")report.status="cancelled";else throw new Error("Only an open lost report or found report awaiting office intake can be closed.");report.updated_at=mockTimestamp(0);return {report:mockReportView(report,false),message:"Report closed."};}
 }
 if(path==="/api/claims"&&method==="GET"){
  const internal=currentUser&&currentUser.role==="office",queue=parsed.searchParams.get("queue")||"all";
  let filtered=mockStore.claims.filter(c=>internal||c.claimant_id===currentUser.id);
  if(internal&&queue==="disputed")filtered=filtered.filter(c=>c.status==="disputed");
  if(internal&&queue==="pending")filtered=filtered.filter(c=>c.status==="pending");
  if(internal&&queue==="active")filtered=filtered.filter(c=>["pending","disputed","needs_more_evidence"].includes(c.status));
  if(internal&&queue==="handover")filtered=filtered.filter(c=>c.status==="approved_for_collection");
  if(internal&&queue==="other")filtered=filtered.filter(c=>!["pending","disputed","needs_more_evidence","approved_for_collection"].includes(c.status));
  const activeCount=internal?null:filtered.filter(c=>["pending","disputed","needs_more_evidence"].includes(c.status)).length;
  filtered.sort((a,b)=>internal?a.created_at.localeCompare(b.created_at):b.created_at.localeCompare(a.created_at));
  const pageSize=Math.max(1,Math.min(100,Number(parsed.searchParams.get("page_size")||50)));
  const offset=Math.max(0,Number(parsed.searchParams.get("cursor")||0));
  const page=filtered.slice(offset,offset+pageSize),hasMore=offset+pageSize<filtered.length;
  return {claims:page.map(c=>mockClaimView(c,Boolean(internal))),next_cursor:hasMore?String(offset+pageSize):null,has_more:hasMore,active_count:activeCount};
 }
 if(path==="/api/claims"&&method==="POST"){
  if(!currentUser||currentUser.role!=="student")throw new Error("Claims must be submitted from a student account.");
  const report=mockStore.reports.find(r=>r.id===body.report_id);if(!report||report.report_type!=="found"||report.status!=="available")throw new Error("This item is not accepting claims.");
  if(report.created_by===currentUser.id)throw new Error("You cannot claim your own found-item report.");
  if(mockStore.claims.some(c=>c.report_id===report.id&&c.claimant_id===currentUser.id&&["pending","disputed","needs_more_evidence","approved_for_collection","rejected"].includes(c.status)))throw new Error("You already have a claim for this item. Follow the existing review.");
  const types=Array.isArray(body.evidence_types)?body.evidence_types:[];if(!types.length)throw new Error("Choose at least one proof type.");
  const conflict=mockStore.claims.some(c=>c.report_id===report.id&&["pending","disputed","needs_more_evidence"].includes(c.status));
  if(conflict)mockStore.claims.filter(c=>c.report_id===report.id&&["pending","disputed","needs_more_evidence"].includes(c.status)).forEach(c=>c.status="disputed");
  const claim={id:"mock-claim-"+Math.random().toString(36).slice(2,10),report_id:report.id,lost_report_id:body.lost_report_id||null,claimant_id:currentUser.id,claimant_name:currentUser.display_name,claimant_email:currentUser.email,evidence:String(body.evidence||"").trim(),evidence_types:types,status:conflict?"disputed":"pending",appeal_note:null,appeal_count:0,reviewer_note:null,created_at:mockTimestamp(0),updated_at:mockTimestamp(0)};
  mockStore.claims.unshift(claim);mockNotify(MOCK_USERS.office.id,"Claim submitted","A student submitted a claim that needs ownership review.","claim",claim.id,"claim-submitted:"+claim.id);
  return {claim:{id:claim.id,status:claim.status,created_at:claim.created_at},message:"Claim submitted for office review."};
 }
 m=path.match(/^\/api\/claims\/([^/]+)\/(evidence-image|evidence|dispute|decision|handover)$/);
 if(m){
  const id=decodeURIComponent(m[1]),action=m[2],claim=mockStore.claims.find(c=>c.id===id);if(!claim)throw new Error("Claim not found.");const report=mockStore.reports.find(r=>r.id===claim.report_id);
  if(action==="evidence-image"&&method==="POST"){if(currentUser.role!=="student"||claim.claimant_id!==currentUser.id)throw new Error("This is private claim evidence.");const file=body instanceof FormData?body.get("file"):null,data=await mockFileDataUrl(file);if(data)mockStore.evidenceImages[id]=data;return {ok:true,message:"Demo evidence image is held in memory only."};}
  if(action==="evidence-image"&&method==="GET"){if(currentUser.role!=="office"&&claim.claimant_id!==currentUser.id)throw new Error("Evidence image is private.");return {ok:true};}
  if(action==="evidence"&&method==="POST"){if(currentUser.role!=="student"||claim.claimant_id!==currentUser.id)throw new Error("This action is available to the claimant.");if(claim.status!=="needs_more_evidence")throw new Error("The office has not requested additional evidence.");claim.evidence=String(body.evidence||"").trim();claim.status="pending";claim.updated_at=mockTimestamp(0);mockNotify(MOCK_USERS.office.id,"Additional evidence submitted","The claimant added requested evidence.","claim",id,"evidence-added:"+id+":"+claim.updated_at);return {claim:{id,status:claim.status},message:"Additional evidence submitted."};}
  if(action==="dispute"&&method==="POST"){if(currentUser.role!=="student"||claim.claimant_id!==currentUser.id)throw new Error("This action is available to the claimant.");if(claim.status!=="rejected"||Number(claim.appeal_count||0)>=1)throw new Error("This claim is not eligible for another review request.");claim.status="disputed";claim.appeal_note=String(body.reason||"").trim();claim.appeal_count=1;claim.updated_at=mockTimestamp(0);mockNotify(MOCK_USERS.office.id,"Claim decision review requested","A claimant requested a review.","claim",id,"claim-appeal:"+id);return {claim:{id,status:claim.status},message:"Review request submitted."};}
  if(action==="decision"&&method==="POST"){
   mockRequireOffice();if(["rejected","approved_for_collection","returned"].includes(claim.status))throw new Error("This claim has already reached a final review state.");
   if(body.action==="approve"){
    const competitors=mockStore.claims.some(c=>c.id!==id&&c.report_id===claim.report_id&&["pending","disputed","needs_more_evidence"].includes(c.status));if(competitors)throw new Error("Other active claims exist. Resolve competing claims before approving this one.");
    if(report.status!=="available")throw new Error("The item is not available for claim approval.");
    const selected=[...new Set(body.verification_checks||[])],level=Number(report.verification_level||3),min=({1:2,2:3,3:4,4:4})[level]||4;
    if(selected.length<min)throw new Error("Verification level L"+level+" requires at least "+min+" distinct checks.");
    if(!selected.includes("claimant_identity"))throw new Error("Confirm the claimant's identity before approving the claim.");
    if(level>=4&&!selected.includes("authorised_record"))throw new Error("Restricted items require an authorised record/custodian check.");
    claim.verification_checks=selected;claim.status="approved_for_collection";report.status="claim_approved";
   }else if(body.action==="reject")claim.status="rejected";else if(body.action==="request_more_evidence")claim.status="needs_more_evidence";else if(body.action==="mark_disputed")claim.status="disputed";else throw new Error("Unsupported claim decision.");
   claim.reviewer_note=body.note||null;claim.updated_at=mockTimestamp(0);mockNotify(claim.claimant_id,body.action==="approve"?"Claim verified":"Claim review updated",body.action==="approve"?"Your claim passed office verification. Physical handover is still required.":"The office updated the review for your claim.","claim",id,"claim-decision:"+id+":"+claim.status);
   return {claim:{id,status:claim.status},message:"Claim review updated. Physical collection is not recorded by this module."};
  }
  if(action==="handover"&&method==="POST"){
   mockRequireOffice();if(claim.status!=="approved_for_collection")throw new Error("Only an office-verified claim can proceed to handover.");
   if(!body.confirmed_physical_handover||!body.claimant_identity_checked)throw new Error("Confirm identity and physical handover.");
   if(String(body.tag_id||"").trim()!==String(report.tag_id||""))throw new Error("The physical Tag ID does not match the record.");
   claim.status="returned";claim.updated_at=mockTimestamp(0);report.status="returned";report.updated_at=mockTimestamp(0);
   mockStore.ledger.unshift({user_id:claim.claimant_id,points:5,reason:"The reported item was returned to a verified owner",report_id:report.id,created_at:mockTimestamp(0)});
   if(claim.lost_report_id){const lost=mockStore.reports.find(r=>r.id===claim.lost_report_id);if(lost)lost.status="closed";}
   mockNotify(claim.claimant_id,"Item returned","The office recorded the verified return.","claim",id,"mock-return:"+id);return {claim_id:id,status:"returned",message:"Physical handover recorded."};
  }
 }
 if(path==="/api/notifications"&&method==="GET"){const rows=mockStore.notifications.filter(n=>n.user_id===currentUser.id);return {notifications:mockCopy(rows),unread_count:rows.filter(n=>!n.read_at).length};}
 m=path.match(/^\/api\/notifications\/([^/]+)\/read$/);if(m&&method==="POST"){const n=mockStore.notifications.find(x=>x.id===decodeURIComponent(m[1])&&x.user_id===currentUser.id);if(!n)throw new Error("Notification not found.");n.read_at=mockTimestamp(0);return {ok:true};}
 if(path==="/api/notifications/read-all"&&method==="POST"){mockStore.notifications.filter(n=>n.user_id===currentUser.id&&!n.read_at).forEach(n=>n.read_at=mockTimestamp(0));return {ok:true};}
 if(path==="/api/activity/me"&&method==="GET"){
  if(currentUser.role!=="student")throw new Error("Activity rewards are available to student accounts.");
  const entries=mockStore.ledger.filter(x=>x.user_id===currentUser.id),total=entries.reduce((sum,x)=>sum+x.points,0),milestones=[{tier:"Verified Finder",threshold:20,key:"verified-finder"},{tier:"Campus Helper",threshold:50,key:"campus-helper"},{tier:"Community Champion",threshold:100,key:"community-champion"}],next=milestones.find(x=>total<x.threshold)||null;
  return {total_points:total,rules:{verified_intake:10,verified_return:5},ledger:mockCopy(entries),certificates:mockCopy(mockStore.certificates.filter(c=>c.user_id===currentUser.id)),next_milestone:next,points_to_next_milestone:next?next.threshold-total:0,milestones:milestones.map(x=>({...x,earned:total>=x.threshold}))};
 }
 if(path==="/api/leaderboard"&&method==="GET"){
  const sums=[MOCK_USERS.student,MOCK_USERS.student2].map(u=>({...u,total_points:mockStore.ledger.filter(x=>x.user_id===u.id).reduce((sum,x)=>sum+x.points,0),verified_reports:new Set(mockStore.ledger.filter(x=>x.user_id===u.id).map(x=>x.report_id)).size})).filter(x=>x.total_points>0).sort((a,b)=>b.total_points-a.total_points);
  const leaders=sums.map((x,i)=>({rank:i+1,display_name:x.display_name,total_points:x.total_points,verified_reports:x.verified_reports,is_me:x.id===currentUser.id})),self=leaders.find(x=>x.is_me);
  return {leaders:leaders.slice(0,10),my_rank:self?self.rank:null,my_total_points:self?self.total_points:0,participant_count:leaders.length,updated_at:mockTimestamp(0)};
 }
 if(path==="/api/office/summary"&&method==="GET"){mockRequireOffice();const reports=mockStore.reports,claims=mockStore.claims;return {awaiting_intake:reports.filter(x=>x.report_type==="found"&&x.status==="awaiting_intake").length,available_items:reports.filter(x=>x.report_type==="found"&&x.status==="available").length,active_claims:claims.filter(x=>["pending","disputed","needs_more_evidence"].includes(x.status)).length,disputed_claims:claims.filter(x=>x.status==="disputed").length,approved_handover:claims.filter(x=>x.status==="approved_for_collection").length,returned_items:claims.filter(x=>x.status==="returned").length,total_activity_points:mockStore.ledger.reduce((sum,x)=>sum+x.points,0)};}
 throw new Error("This endpoint is not available in the offline preview: "+method+" "+path);
}

function apiAssetUrl(path) { return /^https?:\/\//i.test(path) ? path : API_BASE_URL + path; }
function imageSourceAttribute(path) {
  if (supabaseClient && typeof path === "string" && path.startsWith("/api/")) return 'data-auth-image="' + escapeHTML(path) + '"';
  return 'src="' + escapeHTML(apiAssetUrl(path)) + '"';
}
let pendingAuthImages = new WeakSet();
async function hydrateAuthImage(img) {
  if (!supabaseClient || pendingAuthImages.has(img) || !img.dataset.authImage) return;
  pendingAuthImages.add(img);
  try {
    const { data } = await supabaseClient.auth.getSession();
    const token = data && data.session ? data.session.access_token : null;
    if (!token) throw new Error("Sign-in required");
    const response = await fetch(API_BASE_URL + img.dataset.authImage, {headers:{Authorization:"Bearer " + token}});
    if (!response.ok) throw new Error("Image request failed");
    const objectUrl = URL.createObjectURL(await response.blob());
    img.dataset.authImageObjectUrl = objectUrl;
    img.src = objectUrl;
  } catch (_) {
    img.alt = "Image unavailable";
    img.classList.add("image-unavailable");
  }
}
function observeAuthImages() {
  const scan = (node) => {
    if (node.nodeType !== 1) return;
    if (node.matches("img[data-auth-image]")) hydrateAuthImage(node);
    if (node.querySelectorAll) node.querySelectorAll("img[data-auth-image]").forEach(hydrateAuthImage);
  };
  const release = (node) => {
    if (node.nodeType !== 1) return;
    const images = [];
    if (node.matches("img[data-auth-image-object-url]")) images.push(node);
    if (node.querySelectorAll) images.push(...node.querySelectorAll("img[data-auth-image-object-url]"));
    images.forEach((img) => { URL.revokeObjectURL(img.dataset.authImageObjectUrl); delete img.dataset.authImageObjectUrl; });
  };
  const observer = new MutationObserver((mutations) => mutations.forEach((mutation) => {
    mutation.addedNodes.forEach(scan);
    mutation.removedNodes.forEach(release);
  }));
  observer.observe(document.body, {childList:true,subtree:true});
  scan(document.body);
}

async function downloadAuthenticatedFile(path, filename) {
  if (!supabaseClient) { window.location.href = apiAssetUrl(path); return; }
  const { data } = await supabaseClient.auth.getSession();
  const token = data && data.session ? data.session.access_token : null;
  if (!token) throw new Error("Please sign in again to download this file.");
  const response = await fetch(API_BASE_URL + path, {headers:{Authorization:"Bearer " + token}});
  if (!response.ok) throw new Error("Download failed (" + response.status + ").");
  const objectUrl = URL.createObjectURL(await response.blob());
  const anchor = document.createElement("a");
  anchor.href = objectUrl;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(objectUrl), 1500);
}
function clearAuthenticatedImages() {
  document.querySelectorAll("img[data-auth-image]").forEach((img) => {
    if (img.dataset.authImageObjectUrl) URL.revokeObjectURL(img.dataset.authImageObjectUrl);
    img.removeAttribute("src");
    img.removeAttribute("data-auth-image");
    delete img.dataset.authImageObjectUrl;
  });
  pendingAuthImages = new WeakSet();
}


async function api(url, options) {
  const opts = Object.assign({ method: "GET", headers: {} }, options || {});
  if (opts.body && !(opts.body instanceof FormData) && typeof opts.body !== "string") {
    opts.body = JSON.stringify(opts.body);
  }
  if (opts.body && !(opts.body instanceof FormData) && !opts.headers["Content-Type"]) {
    opts.headers["Content-Type"] = "application/json";
  }
  if (usingMockApi) return mockApi(url, opts);
  if (supabaseClient) {
    const { data } = await supabaseClient.auth.getSession();
    supabaseAccessToken = data && data.session ? data.session.access_token : null;
    if (supabaseAccessToken) opts.headers.Authorization = "Bearer " + supabaseAccessToken;
  }
  let response;
  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort(), 25000);
  if (opts.signal && typeof AbortSignal.any === "function") {
    opts.signal = AbortSignal.any([opts.signal, controller.signal]);
  } else {
    opts.signal = controller.signal;
  }
  try {
    response = await fetch(API_BASE_URL + url, opts);
  } catch (error) {
    if (error && error.name === "AbortError") {
      throw new Error("The LostLink server took too long to respond. It may be waking from a cold start; please retry.");
    }
    throw new Error("LostLink API is unreachable. Check the backend deployment and API origin.");
  } finally {
    window.clearTimeout(timeoutId);
  }
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(explainError(data, "Request failed (" + response.status + ")."));
  return data;
}

function showToast(message, error) {
  const toast = $("#toast");
  toast.textContent = message;
  toast.classList.toggle("error", Boolean(error));
  toast.classList.remove("hidden");
  window.clearTimeout(showToast.timer);
  showToast.timer = window.setTimeout(() => toast.classList.add("hidden"), 4800);
}

function showNotice(message, error) {
  const notice = $("#notice");
  notice.textContent = message;
  notice.classList.toggle("error", Boolean(error));
  notice.classList.remove("hidden");
  notice.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function statusLabel(status) {
  return STATUS_LABELS[status] || String(status || "Unknown").replace(/_/g, " ");
}

function statusClass(status) {
  return "status-pill status-" + String(status || "").replace(/[^a-z_]/g, "");
}

function humanDate(value) {
  if (!value) return "Date not specified";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}

function humanDateTime(value) {
  if (!value) return "Time not specified";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value).replace("T", " ");
  return date.toLocaleString(undefined, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}

function categoryLabel(value) {
  const found = (appConfig.categories || []).find((c) => c.value === value);
  return found ? found.label : (value || "Item");
}

function applyDateInputBounds() {
  const minDate = "2012-01-01";
  const now = new Date();
  const localNow = new Date(now.getTime() - now.getTimezoneOffset() * 60000);
  const maxDateTime = localNow.toISOString().slice(0, 16);
  const maxDate = maxDateTime.slice(0, 10);
  ["#publicDate", "#publicDateFound", "#publicHandoverAtFound", "#reportDate", "#reportDateFound"].forEach((selector) => {
    const input = $(selector);
    if (!input) return;
    input.min = minDate + "T00:00";
    input.max = maxDateTime;
  });
  ["#filterDateFrom", "#filterDateTo"].forEach((selector) => {
    const input = $(selector);
    if (!input) return;
    input.min = minDate;
    input.max = maxDate;
  });
}

async function loadConfig() {
  appConfig = await api("/api/config");

  // Public reporting and browsing must not depend on the staff-authentication
  // provider. Populate every public and office selector as soon as public
  // configuration is available, before attempting to initialise Supabase.
  const categories = Array.isArray(appConfig.categories) ? appConfig.categories : [];
  const categoryOptions = categories.map((category) =>
    '<option value="' + escapeHTML(category.value) + '">' + escapeHTML(category.label) + "</option>"
  ).join("");
  ["#reportCategory", "#reportCategoryFound"].forEach((selector) => { const node = $(selector); if (node) node.innerHTML = '<option value="">Choose a category</option>' + categoryOptions; });
  $("#filterCategory").innerHTML = '<option value="">All categories</option>' + categoryOptions;
  ["#publicCategory", "#publicCategoryFound"].forEach((selector) => { const node = $(selector); if (node) node.innerHTML = '<option value="">Choose a category</option>' + categoryOptions; });
  $("#publicBrowseCategory").innerHTML = '<option value="">All categories</option>' + categoryOptions;

  const locations = appConfig.locations || {};
  const blocks = Array.isArray(locations.blocks) ? locations.blocks : [];
  const aliases = locations.aliases && typeof locations.aliases === "object" ? locations.aliases : {};
  const formatLocationOption = (block) => {
    const aliasText = Array.isArray(aliases[block]) && aliases[block].length ? " · " + aliases[block].join(" / ") : "";
    return '<option value="' + escapeHTML(block) + '">' + escapeHTML(block + aliasText) + "</option>";
  };
  const blockOptions = blocks.map(formatLocationOption).join("");
  const locationGroups = locations.groups && typeof locations.groups === "object" ? locations.groups : {};
  const groupedPublicOptions = Object.entries(locationGroups).map(([label, entries]) =>
    '<optgroup label="' + escapeHTML(label) + '">' +
    (Array.isArray(entries) ? entries : []).map(formatLocationOption).join("") +
    "</optgroup>"
  ).join("") + '<option value="Other / Not listed">Other / Not listed</option>';
  ["#reportBlock", "#reportBlockFound"].forEach((selector) => { const node = $(selector); if (node) node.innerHTML = '<option value="">Choose a block or area</option>' + blockOptions; });
  $("#filterBlock").innerHTML = '<option value="">All locations</option>' + blockOptions;
  ["#publicBlock", "#publicBlockFound"].forEach((selector) => { const node = $(selector); if (node) node.innerHTML = '<option value="">Choose a building or outdoor area</option>' + groupedPublicOptions; });
  const floorOptions = (Array.isArray(locations.floors) ? locations.floors : []).map((floor) =>
    '<option value="' + escapeHTML(floor) + '">' + escapeHTML(floor) + "</option>"
  ).join("");
  ["#reportFloor", "#reportFloorFound"].forEach((selector) => { const node = $(selector); if (node) node.innerHTML = '<option value="">Not sure</option>' + floorOptions; });
  ["#publicFloor", "#publicFloorFound"].forEach((selector) => { const node = $(selector); if (node) node.innerHTML = '<option value="">Not sure</option>' + floorOptions; });

  if (appConfig.demo_mode) {
    $("#demoAccess").classList.remove("hidden");
    $("#officeAccessModeNote").classList.add("hidden");
  }

  // Supabase is required only for authorised office sign-in. If its browser
  // SDK/configuration is unavailable, keep public Lost/Found/Browse/Track usable.
  if (appConfig.auth_mode === "supabase") {
    $("#demoAccess").classList.add("hidden");
    const modeNote = $("#officeAccessModeNote");
    try {
      if (!appConfig.supabase_url || !appConfig.supabase_anon_key) {
        throw new Error("Supabase Auth configuration is missing.");
      }
      // Use Supabase's documented Auth REST endpoints directly. This removes
      // the third-party browser SDK/CDN from the trusted script supply chain.
      supabaseClient = createSupabaseRestAuthClient(appConfig.supabase_url, appConfig.supabase_anon_key);
      modeNote.textContent = "Live campus deployment: sign in with your verified college account. Office access is limited to the authorised staff email allowlist.";
      modeNote.classList.remove("hidden");
    } catch (error) {
      supabaseClient = null;
      modeNote.textContent = "Office sign-in is unavailable: " + error.message;
      modeNote.classList.remove("hidden");
    }
  } else {
    $("#officeAccessModeNote").classList.add("hidden");
  }

  const localNow = new Date(Date.now() - new Date().getTimezoneOffset() * 60000);
  ["#reportDate", "#reportDateFound"].forEach((selector) => { const node = $(selector); if (node) node.value = localNow.toISOString().slice(0, 16); });
  applyDateInputBounds();
}

function stopNotificationPolling() {
  if (notificationPollTimer !== null) {
    window.clearInterval(notificationPollTimer);
    notificationPollTimer = null;
  }
}

function startNotificationPolling() {
  stopNotificationPolling();
  notificationPollTimer = window.setInterval(async () => {
    if (!currentUser || document.hidden || notificationPollInFlight) return;
    notificationPollInFlight = true;
    try {
      if (!$("#notificationsView").classList.contains("hidden")) {
        await loadNotifications(true);
      } else {
        await refreshNotificationBadge();
      }
    } catch (_) {
      // Polling is best-effort; transient network errors should not interrupt the UI.
    } finally {
      notificationPollInFlight = false;
    }
  }, 10000);
}

function showLogin() {
  showPublicHome();
}

function enterApp(user) {
  if (!user || user.role !== "office") {
    showPublicHome();
    throw new Error("This account does not have a valid LostLink role.");
  }
  currentUser = user;
  if (usingMockApi) mockStore.session = mockCopy(user);
  if ($("#appModeNote")) $("#appModeNote").classList.toggle("hidden", !usingMockApi);
  $("#loginView").classList.add("hidden");
  $("#appView").classList.remove("hidden");
  placeFinnIn("#appView [data-finn-slot]");
  $("#userName").textContent = user.display_name;
  $("#userInitial").textContent = (user.display_name || "U").trim().charAt(0).toUpperCase();
  $("#userInitial").className = "avatar " + (user.role === "office" ? "avatar-office" : "avatar-student");
  $("#roleChip").textContent = user.role === "office" ? "Office staff" : "Student";
  $("#roleChip").className = "role-chip" + (user.role === "office" ? " role-chip-office" : "");
  $$('[data-view="report"], [data-view="my-reports"], [data-view="my-claims"]').forEach((button) => {
    button.classList.toggle("hidden", user.role === "office");
  });
  $("#officeDashboardNav").classList.toggle("hidden", user.role !== "office");
  $("#privacyRequestsNav").classList.toggle("hidden", user.role !== "office");
  $('[data-view="start"]').classList.toggle("hidden", user.role === "office");
  $("#welcomeTitle").textContent = user.role === "office" ? "Manage found items and claims." : "Find what you are looking for.";
  $("#welcomeSubtitle").textContent = user.role === "office"
    ? "Confirm physical intake and review claims before authorising the next step."
    : "Search office-held items, compare possible matches and submit a private claim.";
  $("#studentNav").classList.remove("hidden");
  navigate(user.role === "office" ? "office" : "start");
  startNotificationPolling();
}

function setFinnMessage(message, awake = true) {
  const dock = $("#finnDock");
  const note = $("#mascotMessage");
  if (!dock || !note) return;
  note.textContent = message;
  dock.classList.add("has-tip");
  if (awake) {
    dock.classList.remove("is-awake");
    void dock.offsetWidth;
    dock.classList.add("is-awake");
  }
}
function updateFinnForView(view) {
  const messages = {
    browse: "Let's look through the found-item desk. Try a category or a few details.",
    report: "Tell me what happened. Clear visible details help me find better matches.",
    "my-reports": "I’m checking your case notes. Open a report to see its possible matches.",
    "my-claims": "I’ll keep an eye on your claim. The campus team handles the ownership checks.",
    notifications: "New clues land here. I’ll point out match updates and claim decisions.",
    activity: "Every verified return helps the campus community. Nice work!",
    office: "Welcome to the campus desk. Verify the item and claimant before handover."
  };
  setFinnMessage(messages[view] || "Psst… got a campus mystery? I’m on the case.", false);
}
function navigate(view) {
  if (!currentUser) return;
  if (view !== "my-reports") selectedLostReportForMatchId = null;
  if (view === "office" && currentUser.role !== "office") view = "browse";
  if (currentUser.role === "office" && ["report", "my-reports", "my-claims", "activity"].includes(view)) view = "office";
  const sections = {
    start: "#startView", browse: "#browseView", report: "#reportView", "my-reports": "#myReportsView",
    "my-claims": "#myClaimsView", notifications: "#notificationsView",
    activity: "#activityView", office: "#officeView", privacyRequests: "#privacyRequestsView"
  };
  Object.values(sections).forEach((selector) => $(selector).classList.add("hidden"));
  $(sections[view] || sections.browse).classList.remove("hidden");
  $$("[data-view]").forEach((button) => button.classList.toggle("active", button.dataset.view === view));
  $("#notice").classList.add("hidden");
  if (view === "browse") loadBrowse();
  if (view === "my-reports") loadMyReports();
  if (view === "my-claims") loadMyClaims();
  if (view === "office") loadOffice();
  if (view === "privacyRequests") loadOffice("privacyRequests");
  if (view === "notifications") loadNotifications();
  if (view === "activity") loadActivity();
  updateFinnForView(view);
  refreshNotificationBadge();
}

function activeReportForm() { return document.querySelector("#" + (activeReportKind === "found" ? "foundReportForm" : "lostReportForm")); }
function reportField(id, form = activeReportForm()) { if (!form) return null; return form.querySelector("#" + id + (form.id === "foundReportForm" ? "Found" : "")); }
function setReportMode(type) {
  if (!["lost", "found"].includes(type)) return;
  const chooser = $("#reportTypeChooser");
  const form = document.querySelector(type === "found" ? "#foundReportForm" : "#lostReportForm");
  const previousForm = activeReportForm();
  const previousKind = activeReportKind;
  activeReportKind = type;
  document.querySelectorAll("#lostReportForm, #foundReportForm").forEach((item) => { if (item !== form) item.classList.add("hidden"); });
  if (!form || !chooser) {
    console.error("LostLink report form markup is unavailable.");
    showToast("The report form could not be loaded. Refresh the page and try again.", true);
    return;
  }
  const wasOpen = previousForm && !previousForm.classList.contains("hidden");
  if (wasOpen && previousKind !== type) {
    previousForm.reset();
    showToast("Switched report type. The previous draft was cleared to avoid mixing Lost and Found details.", false);
  }
  reportField("reportType", form).value = type;
  chooser.classList.add("hidden");
  form.classList.remove("hidden");
  const lost = type === "lost";
  const categoryButton = form.querySelector(lost ? "#suggestCategoryButton" : "#suggestCategoryButtonFound");
  const categoryStatus = reportField("categorySuggestion", form);
  if (categoryButton) categoryButton.textContent = lost ? "Suggest category with AI" : "Suggest found-item category with AI";
  if (categoryStatus) categoryStatus.textContent = lost
    ? "AI can suggest a category from the details you remember. You choose the final category."
    : "AI can classify the item you discovered from its observable details. Review the suggestion before selecting it.";
  const guidanceTitle = $(".side-guidance h3");
  const guidanceCopy = $(".side-guidance > p");
  const guidanceRules = $(".side-guidance .guidance-rule");
  if (guidanceTitle) guidanceTitle.textContent = lost ? "Help us retrace your steps." : "Help us return this item safely.";
  if (guidanceCopy) guidanceCopy.textContent = lost
    ? "Think about the last place you used or saw the item. Accurate time and location estimates help narrow possible matches."
    : "Record the exact discovery spot and describe only what is safe to share. The item becomes searchable only after office staff confirm physical intake.";
  const ruleContent = lost ? [
    ["Rebuild the timeline", "Tell us when you last remember having it; an honest estimate is better than a guess."],
    ["Keep proof private", "Save one or two distinctive ownership clues for the private claim review."],
    ["Narrow the search", "Add the block, floor, room or nearby place where you last had it."]
  ] : [
    ["Describe what you saw", "Record the item's visible condition without publishing names, IDs or private contents."],
    ["Pinpoint discovery", "Use the place where you found it, not where you later hand it in."],
    ["Complete the handover", "Take the item to the campus office. Staff confirm receipt and assign its LostLink Tag ID."]
  ];
  guidanceRules.forEach((rule, index) => {
    const entry = ruleContent[index];
    if (!entry) return;
    const strong = rule.querySelector("strong");
    const small = rule.querySelector("small");
    if (strong) strong.textContent = entry[0];
    if (small) small.textContent = entry[1];
  });
  $$("[data-report-kind]").forEach((button) => {
    button.classList.toggle("selected", button.dataset.reportKind === type);
    button.setAttribute("aria-pressed", button.dataset.reportKind === type ? "true" : "false");
  });
  if (lost) {
    $("#reportModeTitle").textContent = "Report a lost item";
    $("#reportModeDescription").textContent = "Help us retrace where you last had it. Add the details that could help another student recognise it.";
    reportField("reportFormStepTitle", form).textContent = "What went missing?";
    reportField("reportFormStepHint", form).textContent = "Describe the item and the last moment you remember having it.";
    reportField("reportItemNameLabel", form).textContent = "What item did you lose?";
    reportField("reportDescriptionLabel", form).textContent = "Describe the item you lost";
    reportField("reportDescription", form).placeholder = "What does it look like? Include its type, size, material, condition and any visible details that could help you recognise it.";
    reportField("reportDescriptionHelp", form).textContent = "Keep one or two unique ownership clues private. You can share those later in a claim so the office can verify they match.";
    reportField("reportFeaturesLabel", form).textContent = "Visible details you remember";
    reportField("reportFeatures", form).placeholder = "Colour patterns, stickers, scratches, logos, case or accessories…";
    reportField("reportDateLabel", form).textContent = "When did you last see it?";
    reportField("reportDateHelp", form).textContent = "Enter the last time you remember having the item, not when you noticed it was missing. An estimate is fine.";
    reportField("reportLocationHeading", form).textContent = "Where did you last have it?";
    reportField("reportLocationHelp", form).textContent = "Choose the last place you remember seeing or using the item.";
    reportField("reportBlockLabel", form).textContent = "Last seen block / building";
    reportField("reportAreaLabel", form).textContent = "Last seen nearby place";
    reportField("reportArea", form).placeholder = "e.g. Library reading room, canteen counter, bus bay";
    reportField("reportTitle", form).placeholder = "e.g. Black backpack I lost";
    reportField("reportSubmitLabel", form).textContent = "Submit lost report";
  } else {
    $("#reportModeTitle").textContent = "Report a found item";
    $("#reportModeDescription").textContent = "Help return an item to its owner. Tell us what you found and exactly where it was discovered.";
    reportField("reportFormStepTitle", form).textContent = "What did you find?";
    reportField("reportFormStepHint", form).textContent = "Record the item's visible condition and discovery location.";
    reportField("reportItemNameLabel", form).textContent = "What item did you find?";
    reportField("reportDescriptionLabel", form).textContent = "Describe the item you found";
    reportField("reportDescription", form).placeholder = "Describe the item as you found it: type, size, material, condition and visible identifying details. Do not guess who owns it.";
    reportField("reportDescriptionHelp", form).textContent = "Share only safe, observable details. Do not include names, student IDs, serial numbers, contents or hidden identifying marks.";
    reportField("reportFeaturesLabel", form).textContent = "Visible condition and features";
    reportField("reportFeatures", form).placeholder = "Scratches, stickers, damage, colour, brand, contents visible from outside…";
    reportField("reportDateLabel", form).textContent = "When did you find it?";
    reportField("reportDateHelp", form).textContent = "Enter when you discovered the item. If you are unsure, use your best estimate; office intake time is recorded separately.";
    reportField("reportLocationHeading", form).textContent = "Where did you find it?";
    reportField("reportLocationHelp", form).textContent = "Choose the actual discovery place, not where you later hand it in or where staff store it.";
    reportField("reportBlockLabel", form).textContent = "Found at block / building";
    reportField("reportAreaLabel", form).textContent = "Found near / specific spot";
    reportField("reportArea", form).placeholder = "e.g. Outside Lab 3, under a library desk, near the stairs";
    reportField("reportTitle", form).placeholder = "e.g. Silver water bottle I found";
    reportField("reportSubmitLabel", form).textContent = "Submit found report";
  }
  if (!reportField("reportDate", form).value) {
    const localNow = new Date(Date.now() - new Date().getTimezoneOffset() * 60000);
    reportField("reportDate", form).value = localNow.toISOString().slice(0, 16);
  }
  applyDateInputBounds();
}


function resetReportMode() {
  document.querySelectorAll("#lostReportForm, #foundReportForm").forEach((form) => {
    form.reset();
    form.classList.add("hidden");
  });
  activeReportKind = "lost";
  const setText = (selector, value) => {
    const node = $(selector);
    if (node) node.textContent = value;
  };
  const lostType = $("#reportType");
  const foundType = $("#reportTypeFound");
  if (lostType) lostType.value = "lost";
  if (foundType) foundType.value = "found";
  const chooser = $("#reportTypeChooser");
  if (chooser) chooser.classList.remove("hidden");
  setText("#reportError", "");
  setText("#reportErrorFound", "");
  setText("#imageLabel", "Choose a photo");
  setText("#imageLabelFound", "Choose a photo");
  setText("#categorySuggestion", "AI suggestion is optional. You choose the final category.");
  setText("#categorySuggestionFound", "AI suggestion is optional. You choose the final category.");
  setText("#reportModeTitle", "Choose your report type");
  setText("#reportModeDescription", "Lost and Found have separate guided paths so each report starts with the right context.");
  $$("[data-report-kind]").forEach((button) => {
    button.classList.remove("selected");
    button.setAttribute("aria-pressed", "false");
  });
}


function evidenceTypeLabel(value) {
  const labels = {
    distinctive_features: "Distinctive features",
    purchase_or_receipt: "Purchase / receipt proof",
    packaging_or_accessory: "Packaging or paired accessory",
    timeline_and_location: "Date and location context",
    device_or_account_context: "Device / account context",
    other: "Other verifiable evidence"
  };
  return labels[value] || value;
}

function buildQuery(formValues) {
  const params = new URLSearchParams();
  Object.keys(formValues).forEach((key) => {
    if (formValues[key] !== undefined && formValues[key] !== null && String(formValues[key]).trim() !== "") {
      params.set(key, String(formValues[key]).trim());
    }
  });
  return params.toString();
}

function pageUrl(path, cursor) {
  const url = new URL(path, window.location.origin);
  url.searchParams.set("page_size", String(PAGE_SIZE));
  if (cursor) url.searchParams.set("cursor", cursor);
  else url.searchParams.delete("cursor");
  return url.pathname + url.search;
}

function updatePageButton(buttonId, state) {
  const button = $(buttonId);
  if (!button) return;
  button.classList.toggle("hidden", !state.hasMore && !state.loading);
  button.disabled = Boolean(state.loading);
  button.textContent = state.loading ? "Loading…" : "Load more";
}

async function fetchAllPages(path) {
  const results = [];
  let cursor = null;
  do {
    const page = await api(pageUrl(path, cursor));
    results.push(...(page.reports || []));
    cursor = page.next_cursor || null;
    if (!page.has_more) break;
  } while (cursor);
  return results;
}

function itemCard(report, options) {
  const opts = options || {};
  const icon = CATEGORY_ICONS[report.category] || "◌";
  const visual = report.image_url
    ? '<div class="item-visual"><img ' + imageSourceAttribute(report.image_url) + ' alt="Item photograph" loading="lazy"></div>'
    : '<div class="item-visual"><span class="visual-glyph" aria-hidden="true">' + icon + "</span></div>";
  const claimButton = opts.claim && report.report_type === "found" && report.status === "available"
    ? '<button class="button button-primary button-small" type="button" data-claim="' + escapeHTML(report.id) + '" data-public-ref="' + escapeHTML(report.public_ref || "") + '">Submit private claim ↗</button>'
    : "";
  const detailsButton = '<button class="button button-quiet button-small" type="button" data-view-details="' + escapeHTML(report.id) + '">View details</button>';
  const characteristics = [
    report.brand ? "Brand: " + report.brand : "",
    report.primary_color ? "Colour: " + report.primary_color : "",
    report.visible_features ? report.visible_features : ""
  ].filter(Boolean);
  const characteristicBlock = characteristics.length
    ? '<div class="characteristic-list">' + characteristics.map((value) => '<span class="characteristic-chip">' + escapeHTML(value) + '</span>').join("") + '</div>'
    : "";
  const reasons = opts.reasons && opts.reasons.length
    ? '<ul class="reason-list">' + opts.reasons.map((reason) => "<li>" + escapeHTML(reason) + "</li>").join("") + "</ul>"
    : "";
  const strength = opts.strength
    ? '<span class="strength-pill strength-' + escapeHTML(opts.strength) + '">' + escapeHTML(opts.strength) + " match</span>"
    : "";
  return '<article class="item-card">' + visual +
    '<div class="item-card-body"><div class="item-topline"><span class="item-ref">' + escapeHTML(report.public_ref) + "</span>" +
    '<span class="category-pill">' + escapeHTML(report.category_label || categoryLabel(report.category)) + "</span></div>" +
    "<h3>" + escapeHTML(report.title) + "</h3>" +
    '<p class="item-description">' + escapeHTML(report.description) + "</p>" +
    characteristicBlock + reasons +
    '<div class="item-meta"><span><b>⌖</b>' + escapeHTML(report.location || "Location not specified") + "</span>" +
    '<span><b>◷</b>' + escapeHTML(humanDate(report.occurred_at)) + "</span></div>" +
    '<div class="item-actions">' + strength + detailsButton + claimButton + "</div></div></article>";
}

async function loadBrowse(append = false) {
  if (!currentUser) return;
  const state = pageState.browse;
  if (state.loading) return;
  if (!append) state.cursor = null;
  state.loading = true;
  updatePageButton("#browseLoadMore", state);
  const query = buildQuery({
    q: $("#filterQuery").value,
    category: $("#filterCategory").value,
    block: $("#filterBlock").value,
    room: $("#filterRoom") ? $("#filterRoom").value : "",
    date_from: $("#filterDateFrom") ? $("#filterDateFrom").value : "",
    date_to: $("#filterDateTo") ? $("#filterDateTo").value : ""
  });
  if (append && state.query !== query) {
    append = false;
    state.cursor = null;
    $("#browseResults").innerHTML = "";
    lastKnownReports = [];
  }
  state.query = query;
  try {
    const path = "/api/reports" + (query ? "?" + query : "");
    const data = await api(pageUrl(path, append ? state.cursor : null));
    const reports = data.reports || [];
    lastKnownReports = append ? lastKnownReports.concat(reports) : reports;
    const html = reports.map((report) => itemCard(report, { claim: true })).join("");
    if (append) $("#browseResults").insertAdjacentHTML("beforeend", html);
    else $("#browseResults").innerHTML = html;
    $("#browseCount").textContent = lastKnownReports.length + (lastKnownReports.length === 1 ? " item loaded" : " items loaded");
    $("#browseEmpty").classList.toggle("hidden", lastKnownReports.length > 0);
    state.cursor = data.next_cursor || null;
    state.hasMore = Boolean(data.has_more && state.cursor);
  } catch (error) {
    showToast(error.message, true);
  } finally {
    state.loading = false;
    updatePageButton("#browseLoadMore", state);
  }
}

function resetSearch() {
  $("#filterQuery").value = "";
  $("#filterCategory").value = "";
  $("#filterBlock").value = "";
  if ($("#filterRoom")) $("#filterRoom").value = "";
  if ($("#filterDateFrom")) $("#filterDateFrom").value = "";
  if ($("#filterDateTo")) $("#filterDateTo").value = "";
  loadBrowse();
}

async function suggestReportCategory(event) {
  const form = event?.currentTarget?.closest("form") || activeReportForm();
  if (!form) return;
  const button = form.querySelector(form.id === "foundReportForm" ? "#suggestCategoryButtonFound" : "#suggestCategoryButton");
  const output = reportField("categorySuggestion", form);
  const payload = {
    title: reportField("reportTitle", form).value.trim(),
    description: reportField("reportDescription", form).value.trim(),
    brand: reportField("reportBrand", form).value.trim() || null,
    primary_color: reportField("reportColor", form).value.trim() || null,
    visible_features: reportField("reportFeatures", form).value.trim() || null
  };
  if (payload.title.length < 4 || payload.description.length < 10) {
    output.textContent = "Enter an item name (at least 4 characters) and a description (at least 10 characters) before requesting a suggestion.";
    (payload.title.length < 4 ? reportField("reportTitle", form) : reportField("reportDescription", form)).focus();
    return;
  }
  button.disabled = true;
  button.innerHTML = '<span aria-hidden="true">◌</span> Analysing…';
  output.textContent = "Reviewing the item details…";
  try {
    const result = await api("/api/reports/category-suggestion", { method: "POST", body: payload });
    const suggestion = result.suggestion || {};
    if (suggestion.status !== "suggested" || !suggestion.category) {
      output.textContent = "No reliable category suggestion was found. Please choose the category manually.";
      return;
    }
    const alternatives = (suggestion.alternatives || []).slice(0, 3);
    output.innerHTML = '<span class="ai-suggestion-title">Suggested: <strong>' +
      escapeHTML(suggestion.label || categoryLabel(suggestion.category)) + '</strong></span>' +
      '<span class="ai-suggestion-actions">' +
      alternatives.map((item) => '<button class="ai-alternative-button" type="button" data-use-category="' +
        escapeHTML(item.category) + '">' + escapeHTML(item.label || categoryLabel(item.category)) +
        (item.category === suggestion.category ? ' · Apply' : ' · Use instead') + '</button>').join("") +
      '</span><span class="ai-suggestion-note">AI suggestions are advisory. Select one to apply it; no field is changed automatically.</span>';
  } catch (error) {
    output.textContent = "AI suggestion unavailable: " + (error.message || "choose a category manually.");
  } finally {
    button.disabled = false;
    button.innerHTML = '<span aria-hidden="true">✦</span> Suggest with AI';
  }
}

async function submitReport(event) {
  event.preventDefault();
  const form = event.currentTarget;
  activeReportKind = form.id === "foundReportForm" ? "found" : "lost";
  const errorNode = reportField("reportError", form);
  if (!form || !errorNode) {
    showToast("The report form is unavailable. Refresh the page and try again.", true);
    return;
  }
  errorNode.textContent = "";
  const reportType = reportField("reportType", form).value;
  if (!reportType) {
    errorNode.textContent = "Choose whether you lost or found the item first.";
    return;
  }
  const body = {
    report_type: reportType,
    title: reportField("reportTitle", form).value.trim(),
    category: reportField("reportCategory", form).value,
    description: reportField("reportDescription", form).value.trim(),
    brand: reportField("reportBrand", form).value.trim() || null,
    primary_color: reportField("reportColor", form).value.trim() || null,
    visible_features: reportField("reportFeatures", form).value.trim() || null,
    occurred_at: reportField("reportDate", form).value || null,
    location_block: reportField("reportBlock", form).value || null,
    location_floor: reportField("reportFloor", form).value || null,
    location_room: reportField("reportRoom", form).value.trim() || null,
    location_area: reportField("reportArea", form).value.trim() || null,
    image_ai_consent: Boolean(reportField("imageAiConsent", form)?.checked)
  };
  const image = reportField("reportImage", form).files[0];
  if (!body.location_block && !body.location_area) {
    errorNode.textContent = "Choose a campus block/building or enter a nearby area.";
    reportField("reportArea", form).focus();
    return;
  }
  if (reportSubmitting) return;
  reportSubmitting = true;
  const submitButton = form.querySelector('button[type="submit"]');
  if (!submitButton) {
    reportSubmitting = false;
    errorNode.textContent = "The report submit button is missing. Refresh the page and try again.";
    return;
  }
  submitButton.disabled = true;
  try {
    const result = await api("/api/reports", { method: "POST", body });
    let successMessage = result.message;
    let photoFailed = false;
    if (image) {
      const fileBody = new FormData();
      fileBody.append("file", image);
      try {
        await api("/api/reports/" + encodeURIComponent(result.report.id) + "/image", { method: "POST", body: fileBody });
        if (appConfig && appConfig.image_enrichment_enabled) {
          try {
            const ai = await api("/api/reports/" + encodeURIComponent(result.report.id) + "/enrichment", { method: "POST" });
            const enrichment = ai.enrichment || {};
            if (enrichment.status === "completed" && enrichment.caption) {
              successMessage += " AI photo suggestion: " + enrichment.caption +
                (enrichment.keywords && enrichment.keywords.length ? " Suggested keywords: " + enrichment.keywords.join(", ") + "." : "");
            } else if (enrichment.status === "unavailable") {
              successMessage += " AI photo suggestions could not be generated; your report and photo were saved.";
            }
          } catch (_) {
            successMessage += " AI photo suggestions were unavailable; your report and photo were saved.";
          }
        }
      } catch (uploadError) {
        photoFailed = true;
        successMessage += " The report was saved, but the photo upload failed: " + uploadError.message;
      }
    }
    resetReportMode();
    navigate("my-reports");
    showToast(successMessage, photoFailed);
  } catch (error) {
    errorNode.textContent = error.message;
  } finally {
    reportSubmitting = false;
    submitButton.disabled = false;
  }
}


async function loadMyReports(append = false) {
  if (!currentUser || currentUser.role !== "student") return;
  const state = pageState.myReports;
  if (state.loading) return;
  if (!append) state.cursor = null;
  state.loading = true;
  updatePageButton("#myReportsLoadMore", state);
  $("#matchesPanel").classList.add("hidden");
  try {
    const data = await api(pageUrl("/api/reports?mine=true", append ? state.cursor : null));
    const reports = data.reports || [];
    lastKnownReports = lastKnownReports.concat(reports);
    const html = reports.map((report) => {
      const matchButton = report.report_type === "lost" && report.status === "open"
        ? '<button class="button button-primary button-small" type="button" data-matches="' + escapeHTML(report.id) + '">Find possible matches</button>' : "";
      const canClose = (report.report_type === "lost" && report.status === "open" && !report.has_active_linked_claim) ||
        (report.report_type === "found" && report.status === "awaiting_intake");
      const closeButton = canClose
        ? '<button class="button button-quiet button-small" type="button" data-close-report="' + escapeHTML(report.id) +
          '" data-close-type="' + escapeHTML(report.report_type) + '">' +
          (report.report_type === "found" ? "Withdraw report" : "Close report") + '</button>' : "";
      const linkedClaimNote = report.report_type === "lost" && report.status === "open" && report.has_active_linked_claim
        ? '<p class="field-hint">This lost report is linked to a claim under review. Resolve the claim before closing the report.</p>' : "";
      const type = report.report_type === "lost" ? "Lost report" : "Found report";
      const imageNote = report.report_type === "found" && report.status === "awaiting_intake"
        ? "The office must confirm physical receipt before the item can appear in search." : "";
      const characteristics = [report.brand ? "Brand: " + report.brand : "", report.primary_color ? "Colour: " + report.primary_color : "", report.visible_features || ""].filter(Boolean);
      const extra = characteristics.length
        ? '<div class="characteristic-list">' + characteristics.map((value) => '<span class="characteristic-chip">' + escapeHTML(value) + '</span>').join("") + '</div>' : "";
      return '<article class="list-card"><div class="list-card-head"><div><h3>' + escapeHTML(report.title) + '</h3><p>' +
        escapeHTML(type + " · " + report.public_ref) + "</p></div><span class=\"" + statusClass(report.status) + "\">" +
        escapeHTML(statusLabel(report.status)) + "</span></div><p>" + escapeHTML(report.description) + "</p>" + extra +
        '<div class="list-card-meta"><span>⌖ ' + escapeHTML(report.location) + "</span><span>◷ " + escapeHTML(humanDate(report.occurred_at)) + "</span></div>" +
        (imageNote ? '<p class="field-hint">' + escapeHTML(imageNote) + "</p>" : "") + linkedClaimNote +
        '<div class="card-actions">' + matchButton + closeButton + "</div></article>";
    }).join("");
    if (append) $("#myReportsList").insertAdjacentHTML("beforeend", html);
    else $("#myReportsList").innerHTML = html;
    $("#myReportsEmpty").classList.toggle("hidden", reports.length === 0 && !append);
    state.cursor = data.next_cursor || null;
    state.hasMore = Boolean(data.has_more && state.cursor);
  } catch (error) { showToast(error.message, true); }
  finally {
    state.loading = false;
    updatePageButton("#myReportsLoadMore", state);
  }
}

async function loadMatches(reportId) {
  selectedLostReportForMatchId = reportId;
  $("#matchesPanel").classList.remove("hidden");
  $("#matchResults").innerHTML = '<div class="list-card"><p>Comparing report details…</p></div>';
  try {
    const result = await api("/api/reports/" + encodeURIComponent(reportId) + "/matches");
    const detailedMatches = result.matches.map((match) => ({
      ...match.report, match_strength: match.strength, match_reasons: match.reasons || []
    }));
    lastKnownReports = lastKnownReports.filter((report) => !detailedMatches.some((match) => match.id === report.id)).concat(detailedMatches);
    $("#matchResults").innerHTML = detailedMatches.map((report) => itemCard(report, {
      claim: true, strength: report.match_strength, reasons: report.match_reasons
    })).join("");
    if (!result.matches.length) {
      $("#matchResults").innerHTML = '<div class="empty-state"><span class="empty-icon">⌕</span><h3>No available matches yet</h3><p>Your report remains active. Try checking again after new found-item reports are received by the office.</p></div>';
    }
    $("#matchesPanel").scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (error) { showToast(error.message, true); }
}

async function loadMyClaims(append = false) {
  if (!currentUser || currentUser.role !== "student") return;
  const state = pageState.myClaims;
  if (state.loading) return;
  if (!append) state.cursor = null;
  state.loading = true;
  updatePageButton("#myClaimsLoadMore", state);
  try {
    const data = await api(pageUrl("/api/claims", append ? state.cursor : null));
    const claims = data.claims || [];
    const activeCount = Number.isFinite(Number(data.active_count))
      ? Number(data.active_count)
      : claims.filter((claim) => ["pending", "disputed", "needs_more_evidence"].includes(claim.status)).length;
    const html = claims.map((claim) => {
      let guidance = "Your claim is awaiting review by authorised office staff.";
      if (claim.status === "disputed") guidance = claim.appeal_note
        ? "You requested a review of the earlier decision. The office must review the dispute before the claim can proceed."
        : "Competing claims exist. The item is on hold until authorised office staff resolve the competing claims.";
      if (claim.status === "needs_more_evidence") guidance = "The office has requested additional evidence. Add relevant details without sharing passwords, PINs or one-time codes.";
      if (claim.status === "approved_for_collection") guidance = "Your claim has been verified. The item is not marked returned until campus staff confirm physical handover.";
      if (claim.status === "returned") guidance = "The office recorded the return of the item. This claim is complete.";
      if (claim.status === "rejected") guidance = Number(claim.appeal_count || 0) < 1
        ? "This claim was not approved. You can request one review by explaining what evidence may have been overlooked."
        : "This claim was not approved after review. No further review request is available in this prototype; contact the campus office if needed.";
      const addEvidence = claim.status === "needs_more_evidence"
        ? '<button class="button button-primary button-small" type="button" data-add-evidence="' + escapeHTML(claim.id) + '">Add evidence</button>' : "";
      const disputeForm = claim.status === "rejected" && Number(claim.appeal_count || 0) < 1
        ? '<div class="claim-dispute-form"><label>Why should this decision be reviewed?<textarea data-dispute-reason="' + escapeHTML(claim.id) + '" rows="3" minlength="20" maxlength="1000" placeholder="Explain which evidence or detail should be reconsidered (at least 20 characters)."></textarea></label><button class="button button-quiet button-small" type="button" data-dispute-claim="' + escapeHTML(claim.id) + '">Request review</button></div>' : "";
      const appealNote = claim.appeal_note ? '<div class="claim-appeal-note"><strong>Your review request</strong><p>' + escapeHTML(claim.appeal_note) + '</p></div>' : "";
      const linkedLost = claim.linked_lost_report
        ? '<div class="linked-report-line"><strong>Linked lost report</strong><span>' + escapeHTML(claim.linked_lost_report.title + " · " + claim.linked_lost_report.public_ref) +
          '</span><span class="' + statusClass(claim.linked_lost_report.status) + '">' + escapeHTML(statusLabel(claim.linked_lost_report.status)) + '</span></div>' : "";
      const evidenceTypes = Array.isArray(claim.evidence_types) ? claim.evidence_types : [];
      const evidenceChips = evidenceTypes.length
        ? '<div class="evidence-type-list"><strong>Proof types</strong>' + evidenceTypes.map((type) => '<span class="characteristic-chip">' + escapeHTML(evidenceTypeLabel(type)) + '</span>').join("") + '</div>' : "";
      const evidencePhoto = claim.evidence_image_available
        ? '<figure class="evidence-image-preview"><img ' + imageSourceAttribute('/api/claims/' + claim.id + '/evidence-image') + ' alt="Your private evidence preview" draggable="false"><figcaption>Private, watermarked preview</figcaption></figure>' : "";
      return '<article class="list-card" data-claim-card="' + escapeHTML(claim.id) + '"><div class="list-card-head"><div><h3>' + escapeHTML(claim.report.title) + '</h3><p>' +
        escapeHTML(claim.report.public_ref + " · Submitted " + humanDate(claim.created_at)) + "</p></div><span class=\"" + statusClass(claim.status) + "\">" +
        escapeHTML(statusLabel(claim.status)) + "</span></div><p>" + escapeHTML(guidance) + '</p>' + appealNote + linkedLost + '<div class="list-card-meta"><span>⌖ ' +
        escapeHTML(claim.report.location) + "</span><span>Reference " + escapeHTML(claim.report.public_ref) + "</span></div>" +
        evidenceChips + evidencePhoto + '<div class="card-actions">' + addEvidence + "</div>" + disputeForm + "</article>";
    }).join("");
    if (append) $("#myClaimsList").insertAdjacentHTML("beforeend", html);
    else $("#myClaimsList").innerHTML = html;
    $("#myClaimsEmpty").classList.toggle("hidden", claims.length === 0 && !append);
    state.cursor = data.next_cursor || null;
    state.hasMore = Boolean(data.has_more && state.cursor);
  } catch (error) { showToast(error.message, true); }
  finally {
    state.loading = false;
    updatePageButton("#myClaimsLoadMore", state);
  }
}

async function openItemDetails(reportId) {
  let report = findReportById(reportId);
  if (!report) {
    showToast("Item details are not loaded yet. Refresh the search or reopen the match list.", true);
    return;
  }
  selectedDetailsReportId = report.id;
  $("#itemDetailsTitle").textContent = report.title || "Item details";
  const facts = [
    ["Reference", report.public_ref],
    ["Category", report.category_label || categoryLabel(report.category)],
    ["Status", statusLabel(report.status)],
    ["Location", report.location || "Not specified"],
    ["Approximate date", humanDateTime(report.occurred_at)],
    ["Brand / make", report.brand],
    ["Main colour", report.primary_color],
    ["Visible characteristics", report.visible_features],
    ["Record updated", humanDateTime(report.updated_at)]
  ].filter((fact) => fact[1]);
  const photo = report.image_url
    ? '<div class="item-detail-photo-wrap"><img class="item-detail-photo" ' + imageSourceAttribute(report.image_url) + ' alt="Watermarked item preview" draggable="false"><small>Watermarked preview · public item details only</small></div>'
    : "";
  const matchDetails = report.match_reasons && report.match_reasons.length
    ? '<section class="match-detail-block"><h3>Why it was suggested</h3><p class="muted">These are comparison signals, not proof of ownership.</p><ul class="reason-list">' +
      report.match_reasons.map((reason) => "<li>" + escapeHTML(reason) + "</li>").join("") + '</ul><span class="strength-pill strength-' + escapeHTML(report.match_strength || "moderate") + '">' +
      escapeHTML(report.match_strength || "Possible") + " match</span></section>"
    : "";
  $("#itemDetailsContent").innerHTML = photo + '<p class="item-detail-description">' + escapeHTML(report.description || "") + '</p><dl class="item-detail-grid">' +
    facts.map(([key, value]) => '<div><dt>' + escapeHTML(key) + '</dt><dd>' + escapeHTML(value) + '</dd></div>').join("") +
    '</dl>' + matchDetails + '<p class="field-hint">Keep hidden marks, serial numbers and access codes private. Ownership is verified separately by office staff.</p>';
  const canClaim = report.report_type === "found" && report.status === "available";
  $("#itemDetailsClaimButton").classList.toggle("hidden", !canClaim);
  $("#itemDetailsDialog").showModal();
}

function openClaim(reportId) {
  const report = findReportById(reportId);
  if (!report) {
    // The report can come from a match card not currently stored in the browse response.
    loadClaimReport(reportId);
    return;
  }
  selectedClaimReport = report;
  showClaimDialog(report);
}

let lastKnownReports = [];
let selectedDetailsReportId = null;
function findReportById(id) {
  return lastKnownReports.find((report) => report.id === id) || null;
}

async function loadClaimReport(reportId) {
  return openPublicClaimById(reportId);
}

function showClaimDialog(report) {
  openPublicClaimDialog(report);
}

async function loadClaimLostReports(preferredReportId) {
  const select = $("#claimLostReport");
  const requestId = ++lostReportOptionsRequest;
  select.disabled = true;
  select.innerHTML = '<option value="">Loading your open lost reports…</option>';
  try {
    const allReports = await fetchAllPages("/api/reports?mine=true&report_type=lost");
    if (requestId !== lostReportOptionsRequest) return;
    const openReports = allReports.filter((item) => item.report_type === "lost" && item.status === "open");
    select.innerHTML = '<option value="">No linked lost report</option>' + openReports.map((item) =>
      '<option value="' + escapeHTML(item.id) + '">' + escapeHTML(item.title + " · " + item.public_ref + " · " + humanDate(item.occurred_at)) + '</option>'
    ).join("");
    if (preferredReportId && openReports.some((item) => item.id === preferredReportId)) {
      select.value = preferredReportId;
    }
    if (!openReports.length) {
      select.innerHTML = '<option value="">No open lost reports to link</option>';
    }
    select.disabled = false;
    $("#claimSubmitButton").disabled = false;
  } catch (error) {
    if (requestId !== lostReportOptionsRequest) return;
    select.innerHTML = '<option value="">Continue without linking a lost report</option>';
    select.disabled = false;
    $("#claimSubmitButton").disabled = false;
    showToast("Could not load your open lost reports. You can still submit the claim without linking one.", true);
  }
}

async function submitClaim(event) {
  event.preventDefault();
  if (!selectedClaimReport || claimSubmitting) return;
  $("#claimError").textContent = "";
  const evidenceTypes = $$('input[name="claimEvidenceType"]:checked').map((input) => input.value);
  if (!evidenceTypes.length) {
    $("#claimError").textContent = "Select at least one kind of evidence before submitting.";
    return;
  }
  const evidenceImage = $("#claimEvidenceImage").files[0];
  claimSubmitting = true;
  $("#claimSubmitButton").disabled = true;
  try {
    const result = await api("/api/claims", {
      method: "POST",
      body: {
        report_id: selectedClaimReport.id,
        lost_report_id: $("#claimLostReport").value || null,
        evidence: $("#claimEvidence").value.trim(),
        evidence_types: evidenceTypes
      }
    });
    let resultMessage = result.message + " Your evidence is private.";
    let imageFailed = false;
    if (evidenceImage) {
      const fileBody = new FormData();
      fileBody.append("file", evidenceImage);
      try {
        await api("/api/claims/" + encodeURIComponent(result.claim.id) + "/evidence-image", { method: "POST", body: fileBody });
        resultMessage += " The supporting image was attached.";
      } catch (uploadError) {
        imageFailed = true;
        resultMessage += " The text claim was saved, but the photo was rejected: " + uploadError.message;
      }
    }
    $("#claimDialog").close();
    showToast(resultMessage, imageFailed);
    navigate("my-claims");
  } catch (error) {
    $("#claimError").textContent = error.message;
  } finally {
    claimSubmitting = false;
    $("#claimSubmitButton").disabled = false;
  }
}

function openAdditionalEvidence(claimId) {
  selectedEvidenceClaimId = claimId;
  const card = document.querySelector('[data-claim-card="' + CSS.escape(claimId) + '"]');
  const itemTitle = card ? card.querySelector("h3").textContent : "this item";
  $("#additionalEvidenceSummary").textContent = "Add the evidence requested for " + itemTitle + ". This response is private to you and authorised office reviewers.";
  $("#additionalEvidenceText").value = "";
  $("#additionalEvidenceError").textContent = "";
  $("#saveAdditionalEvidenceButton").disabled = false;
  $("#additionalEvidenceDialog").showModal();
}

async function submitAdditionalEvidence(event) {
  event.preventDefault();
  if (!selectedEvidenceClaimId) return;
  const evidence = $("#additionalEvidenceText").value.trim();
  if (evidence.length < 20) {
    $("#additionalEvidenceError").textContent = "Please provide at least 20 characters of relevant evidence.";
    $("#additionalEvidenceText").focus();
    return;
  }
  $("#additionalEvidenceError").textContent = "";
  $("#saveAdditionalEvidenceButton").disabled = true;
  try {
    const result = await api("/api/claims/" + encodeURIComponent(selectedEvidenceClaimId) + "/evidence", {
      method: "POST", body: { evidence }
    });
    $("#additionalEvidenceDialog").close();
    selectedEvidenceClaimId = null;
    showToast(result.claim.message, false);
    await loadMyClaims();
  } catch (error) {
    $("#additionalEvidenceError").textContent = error.message;
  } finally {
    $("#saveAdditionalEvidenceButton").disabled = false;
  }
}

async function loadOffice(appendKey = null) {
  if (!currentUser || currentUser.role !== "office") return;
  const definitions = {
    intake: { path: "/api/reports?report_type=found&status=awaiting_intake", target: "#intakeQueue", button: "#intakeLoadMore", empty: "#intakeEmpty", key: "reports", render: intakeCard },
    inventory: { path: "/api/reports?report_type=found&status=available,claim_approved", target: "#officeInventory", button: "#inventoryLoadMore", empty: "#officeInventoryEmpty", key: "reports", render: officeInventoryCard },
    officeClaims: { path: "/api/claims?queue=active", target: "#officeClaims", button: "#officeClaimsLoadMore", empty: "#officeClaimsEmpty", key: "claims", render: officeClaimCard },
    handovers: { path: "/api/claims?queue=handover", target: "#handoverQueue", button: "#handoverLoadMore", empty: "#handoverEmpty", key: "claims", render: officeHandoverCard },
    privacyRequests: { path: "/api/office/privacy-requests", target: "#privacyRequestsList", button: null, empty: "#privacyRequestsEmpty", key: "requests", render: privacyRequestCard }
  };
  const keys = appendKey ? [appendKey] : Object.keys(definitions);
  if (appendKey && !definitions[appendKey]) return;
  try {
    if (!appendKey) {
      const summary = await api("/api/office/summary");
      $("#officeStats").innerHTML = [
        ["Awaiting intake", summary.awaiting_intake],
        ["Items available", summary.available_items],
        ["Active claims", summary.active_claims],
        ["Disputed claims", summary.disputed_claims],
        ["Ready for handover", summary.approved_handover || 0],
        ["Items returned", summary.returned_items || 0]
      ].map((stat) => '<div class="stat-card"><span>' + escapeHTML(stat[0]) + '</span><strong>' + escapeHTML(stat[1]) + "</strong></div>").join("");
      keys.forEach((key) => {
        pageState[key].cursor = null;
        pageState[key].items = [];
        pageState[key].hasMore = false;
      });
    }
    await Promise.all(keys.map(async (key) => {
      const definition = definitions[key];
      const state = pageState[key];
      if (state.loading) return;
      state.loading = true;
      updatePageButton(definition.button, state);
      try {
        const data = await api(pageUrl(definition.path, appendKey ? state.cursor : null));
        const items = data[definition.key] || [];
        state.items = appendKey ? state.items.concat(items) : items;
        const html = items.map(definition.render).join("");
        if (appendKey) $(definition.target).insertAdjacentHTML("beforeend", html);
        else $(definition.target).innerHTML = html;
        $(definition.empty).classList.toggle("hidden", state.items.length > 0);
        state.cursor = data.next_cursor || null;
        state.hasMore = Boolean(data.has_more && state.cursor);
      } finally {
        state.loading = false;
        updatePageButton(definition.button, state);
      }
    }));
    refreshNotificationBadge();
  } catch (error) { showToast(error.message, true); }
}

function privacyRequestCard(request) {
  const subject = request.account_email || (request.public_reference ? "Public case " + request.public_reference : "Account " + request.user_id);
  const type = ({access:"Access / data copy",correction:"Correction",erasure:"Erasure"})[request.request_type] || request.request_type;
  const status = ({pending:"Awaiting review",in_review:"In review",completed:"Completed",declined:"Declined"})[request.status] || request.status;
  const terminal = ["completed","declined"].includes(request.status);
  return '<article class="list-card"><div class="list-card-head"><div><h3>' + escapeHTML(type) + '</h3><p>' +
    escapeHTML(subject) + " · " + escapeHTML(humanDateTime(request.created_at)) + '</p></div><span class="status-pill">' +
    escapeHTML(status) + '</span></div><p>' + escapeHTML(request.details || "No additional details supplied.") + '</p>' +
    (request.reviewer_note ? '<p class="field-hint"><strong>Last review note:</strong> ' + escapeHTML(request.reviewer_note) + '</p>' : '') +
    (terminal ? '<p class="field-hint">This request is closed.</p>' : '<div class="card-actions"><button class="button button-primary button-small" type="button" data-privacy-review="' +
      escapeHTML(request.id) + '" data-privacy-type="' + escapeHTML(request.request_type) + '" data-privacy-subject="' + escapeHTML(subject) +
      '">Review request</button></div>') + '</article>';
}

let selectedPrivacyRequestId = null;
function openPrivacyDecision(requestId, requestType, subject) {
  selectedPrivacyRequestId = requestId;
  $("#privacyDecisionSummary").textContent = requestType + " request · " + subject;
  $("#privacyDecisionAction").value = "in_review";
  $("#privacyDecisionNote").value = "";
  $("#privacyDecisionError").textContent = "";
  $("#privacyDecisionDialog").showModal();
}
async function submitPrivacyDecision(event) {
  event.preventDefault();
  if (!selectedPrivacyRequestId) return;
  const button = event.currentTarget.querySelector('button[type="submit"]');
  button.disabled = true;
  $("#privacyDecisionError").textContent = "";
  try {
    const result = await api("/api/office/privacy-requests/" + encodeURIComponent(selectedPrivacyRequestId) + "/decision", {
      method: "POST",
      body: {action: $("#privacyDecisionAction").value, note: $("#privacyDecisionNote").value.trim()}
    });
    $("#privacyDecisionDialog").close();
    selectedPrivacyRequestId = null;
    showToast(result.message || "Privacy request updated.", false);
    await loadOffice("privacyRequests");
  } catch (error) {
    $("#privacyDecisionError").textContent = error.message;
  } finally {
    button.disabled = false;
  }
}

function officeInventoryCard(report) {
  return '<article class="list-card"><div class="list-card-head"><div><h3>' +
    escapeHTML(report.title + " · " + report.public_ref) + '</h3><p>' +
    escapeHTML(statusLabel(report.status)) + '</p></div><span class="status-pill status-available">In campus custody</span></div>' +
    '<div class="internal-meta"><span>Physical tag: ' + escapeHTML(report.tag_id) +
    '</span><span>Stored at: ' + escapeHTML(report.storage_location || "Location needs confirmation") + '</span>' +
    '<span>Last updated: ' + escapeHTML(humanDateTime(report.updated_at)) + '</span></div>' +
    '<div class="card-actions"><button class="button button-quiet button-small" type="button" data-storage-update="' +
    escapeHTML(report.id) + '" data-current-location="' + escapeHTML(report.storage_location || "") +
    '">Update storage location</button></div></article>';
}

function officeHandoverCard(claim) {
  const report = claim.report;
  const claimantRoll = claim.claimant_roll_number || "";
  const linkedLostMeta = claim.linked_lost_report
    ? '<div class="linked-report-line office-linked-report"><strong>Linked lost report</strong><span>' +
      escapeHTML(claim.linked_lost_report.title + " · " + claim.linked_lost_report.public_ref) +
      '</span><span class="' + statusClass(claim.linked_lost_report.status) + '">' +
      escapeHTML(statusLabel(claim.linked_lost_report.status)) + '</span></div>'
    : "";
  return '<article class="list-card"><div class="list-card-head"><div><h3>' +
    escapeHTML(report.title + " · " + report.public_ref) + '</h3><p>Claimant: ' +
    escapeHTML(claim.claimant_name) + (claimantRoll ? " · Roll no. " + escapeHTML(claimantRoll) : " · " + escapeHTML(claim.claimant_email)) +
    "</p></div><span class=\"" + statusClass(claim.status) + "\">Verified claim</span></div>" +
    '<div class="internal-meta"><span>Physical tag: ' + escapeHTML(report.tag_id || "Not assigned") +
    "</span><span>Verification level: " + escapeHTML(report.verification_level ? "L" + report.verification_level : "Not assigned") +
    "</span><span>Stored at: " + escapeHTML(report.storage_location || "Location needs confirmation") + "</span></div>" + linkedLostMeta + "<p>Before release, compare the physical item with the tag and verify the claimant under campus policy.</p>" +
    '<div class="card-actions"><button class="button button-primary button-small" type="button" data-handover="' +
    escapeHTML(claim.id) + '" data-tag="' + escapeHTML(report.tag_id || "") + '" data-roll="' + escapeHTML(claimantRoll) + '">Confirm physical handover</button></div></article>';
}

function intakeCard(report) {
  const publicIdentity = report.submission_channel === "public"
    ? '<div class="internal-meta"><strong>Public submission · Roll number: ' + escapeHTML(report.roll_number || "Not supplied") + '</strong>' +
      (report.contact_phone ? '<p>Phone: <a href="tel:' + escapeHTML(report.contact_phone) + '">' + escapeHTML(report.contact_phone) + '</a></p>' : '') +
      (report.contact_email ? '<p>Email: <a href="mailto:' + escapeHTML(report.contact_email) + '">' + escapeHTML(report.contact_email) + '</a></p>' : '') +
      '</div>' +
      '<label class="wide">Verified roll number<input name="verified_roll_number" required minlength="5" maxlength="20" autocomplete="off" placeholder="Read the roll number from the physical college ID"></label>' +
      '<label class="checkbox-line wide"><input type="checkbox" name="identity_verified_in_person" required> I physically checked the reporter’s college ID and confirmed the roll number.</label>'
    : "";
  const submittedHandover = [
    report.item_condition ? "Reported item condition: " + report.item_condition.replaceAll("_", " ") : "",
    report.handover_at ? "Reported handover time: " + humanDateTime(report.handover_at) : "",
    report.handover_recipient ? "Reported recipient: " + report.handover_recipient : "",
    report.handover_note ? "Handover note: " + report.handover_note : ""
  ].filter(Boolean);
  const handoverContext = submittedHandover.length
    ? '<div class="internal-meta">' + submittedHandover.map(value => '<p>' + escapeHTML(value) + '</p>').join("") + '</div>'
    : "";
  return '<article class="list-card"><div class="list-card-head"><div><h3>' + escapeHTML(report.title) + '</h3><p>' +
    escapeHTML(report.public_ref + " · Reported " + humanDate(report.created_at)) + "</p></div><span class=\"" + statusClass(report.status) + "\">Awaiting intake</span></div>" +
    "<p>" + escapeHTML(report.description) + "</p><div class=\"list-card-meta\"><span>⌖ " + escapeHTML(report.location) +
    "</span><span>" + escapeHTML(categoryLabel(report.category)) + "</span></div>" + handoverContext +
    '<form class="intake-form" data-intake-form="' + escapeHTML(report.id) + '">' + publicIdentity +
    '<label class="wide">Campus storage location<input name="storage_location" required minlength="4" maxlength="160" placeholder="Lost & Found room · cabinet A · shelf 01"></label>' +
    '<label class="wide">Private identifying detail / approved verification method<textarea name="private_detail" maxlength="1200" placeholder="Not shown to students. For restricted items, describe the authorised verification method without copying unnecessary sensitive data."></textarea></label>' +
    '<label>Estimated value band<select name="value_band"><option value="unknown">Unknown</option><option value="low">Low</option><option value="medium">Medium</option><option value="high">High</option></select></label>' +
    '<label>Sensitivity level<select name="sensitivity_level"><option value="1">1 · Routine</option><option value="2">2 · Elevated</option><option value="3">3 · Sensitive</option><option value="4">4 · Restricted</option></select></label>' +
    '<label class="checkbox-line wide"><input type="checkbox" name="confirmed_physical_receipt" required> I confirm the physical item is in campus office custody and has been placed at the recorded storage location.</label>' +
    '<div class="wide"><button class="button button-primary button-small" type="submit">Confirm receipt, store & assign tag</button></div></form></article>';
}

function officeClaimCard(claim) {
  const report = claim.report;
  const levelNumber = Number(report.verification_level || 3);
  const level = "L" + levelNumber;
  const minimumChecks = ({ 1: 2, 2: 3, 3: 4, 4: 4 })[levelNumber] || 4;
  const privateDetail = report.private_verification_detail || "No private verification detail recorded.";
  const checks = [
    ["distinctive_features", "Distinctive features / owner-only detail match"],
    ["date_location", "Date and location are consistent"],
    ["physical_inspection", "Physical item inspected"],
    ["supporting_evidence", "Independent supporting evidence reviewed"],
    ["owner_specific_detail", "Owner-specific detail checked"],
    ["claimant_identity", "Claimant identity checked"]
  ];
  if (levelNumber >= 4) checks.push(["authorised_record", "Authorised record / custodian checked"]);
  const checklist = '<div class="verification-checklist"><div class="verification-checklist-heading"><strong>Verification checklist</strong><span>' +
    escapeHTML("Level " + levelNumber + " · minimum " + minimumChecks + " checks") +
    '</span></div><p class="field-hint">Check the evidence you actually reviewed. Claimant identity is always required; restricted items also require an authorised-record check.</p>' +
    '<div class="verification-check-grid">' + checks.map(([value, label]) =>
      '<label class="verify-check"><input type="checkbox" data-verification-check="true" value="' + escapeHTML(value) + '"><span>' + escapeHTML(label) + '</span></label>'
    ).join("") + '</div></div>';
  const claimantPhone = claim.claimant_phone
    ? '<div class="internal-meta">Claimant phone: <a href="tel:' + escapeHTML(claim.claimant_phone) + '">' + escapeHTML(claim.claimant_phone) + '</a></div>'
    : '<div class="internal-meta">Claimant phone: Not provided</div>';
  const reporterPhone = report.contact_phone
    ? '<div class="internal-meta">Found reporter phone: <a href="tel:' + escapeHTML(report.contact_phone) + '">' + escapeHTML(report.contact_phone) + '</a></div>'
    : "";
  const publicIdentity = claim.submission_channel === "public"
    ? '<div class="internal-meta"><strong>Public claim · Roll number: ' + escapeHTML(claim.claimant_roll_number || "Not supplied") + '</strong></div>' +
      '<label class="wide">Verified roll number<input type="text" data-verified-roll required minlength="5" maxlength="20" autocomplete="off" placeholder="Read the roll number from the claimant’s college ID"></label>' +
      '<label class="checkbox-line wide"><input type="checkbox" data-identity-verified> I physically checked the claimant’s college ID and confirmed the roll number.</label>'
    : "";
  const actions = '<div class="decision-note"><input type="text" maxlength="800" data-note-for="' + escapeHTML(claim.id) +
    '" placeholder="Internal review note (optional)"></div><div class="card-actions">' +
    '<button class="button button-primary button-small" type="button" data-decision="approve" data-claim-id="' + escapeHTML(claim.id) + '">Verify claim</button>' +
    '<button class="button button-amber button-small" type="button" data-decision="request_more_evidence" data-claim-id="' + escapeHTML(claim.id) + '">Request evidence</button>' +
    '<button class="button button-danger button-small" type="button" data-decision="mark_disputed" data-claim-id="' + escapeHTML(claim.id) + '">Mark disputed</button>' +
    '<button class="button button-quiet button-small" type="button" data-decision="reject" data-claim-id="' + escapeHTML(claim.id) + '">Reject claim</button></div>';
  const linkedLost = claim.linked_lost_report
    ? '<div class="linked-report-line office-linked-report"><strong>Linked lost report</strong><span>' +
      escapeHTML(claim.linked_lost_report.title + " · " + claim.linked_lost_report.public_ref) +
      '</span><span class="' + statusClass(claim.linked_lost_report.status) + '">' +
      escapeHTML(statusLabel(claim.linked_lost_report.status)) + '</span></div>' +
      (claim.linked_lost_report.private_verification_detail
        ? '<div class="internal-detail"><strong>OWNER-ONLY DETAILS · LOST REPORT</strong><small>' +
          escapeHTML(claim.linked_lost_report.private_verification_detail) + '</small></div>'
        : "")
    : "";
  const evidenceTypes = Array.isArray(claim.evidence_types) ? claim.evidence_types : [];
  const evidenceChips = evidenceTypes.length
    ? '<div class="evidence-type-list"><strong>CLAIMANT-PROVIDED PROOF TYPES</strong>' +
      evidenceTypes.map((type) => '<span class="characteristic-chip">' + escapeHTML(evidenceTypeLabel(type)) + '</span>').join("") + '</div>'
    : "";
  const evidenceImageSource = usingMockApi && mockStore.evidenceImages[claim.id] ? mockStore.evidenceImages[claim.id] : "/api/claims/" + encodeURIComponent(claim.id) + "/evidence-image";
  const evidencePhoto = claim.evidence_image_available
    ? '<figure class="evidence-image-preview"><img ' + imageSourceAttribute(evidenceImageSource) + ' alt="Private claim evidence preview" draggable="false"><figcaption>Private preview · claimant and office only</figcaption></figure>'
    : "";
  return '<article class="list-card" data-claim-card="' + escapeHTML(claim.id) + '" data-verification-level="' + levelNumber + '" data-minimum-checks="' + minimumChecks + '" data-public-claim="' + (claim.submission_channel === "public" ? "true" : "false") + '" data-expected-roll="' + escapeHTML(claim.claimant_roll_number || "") + '"><div class="list-card-head"><div><h3>' +
    escapeHTML(report.title) + " · " + escapeHTML(report.public_ref) +
    '</h3><p>Claimant: ' + escapeHTML(claim.claimant_name) + (claim.claimant_roll_number ? " · Roll no. " + escapeHTML(claim.claimant_roll_number) : " · " + escapeHTML(claim.claimant_email)) + "</p></div><span class=\"" + statusClass(claim.status) +
    "\">" + escapeHTML(statusLabel(claim.status)) + "</span></div>" +
    '<div class="internal-meta"><span>Physical tag: ' + escapeHTML(report.tag_id || "Not assigned") + "</span><span>Verification: " + escapeHTML(level) +
    "</span><span>Value band: " + escapeHTML(report.value_band || "unknown") + "</span><span>Sensitivity: " + escapeHTML(report.sensitivity_level) + "</span></div>" +
    claimantPhone + reporterPhone + linkedLost +
    '<div class="claim-evidence"><strong>CLAIMANT EVIDENCE · PRIVATE</strong><p>' + escapeHTML(claim.evidence) + "</p></div>" +
    evidenceChips + evidencePhoto +
    (claim.appeal_note ? '<div class="claim-appeal-note"><strong>CLAIMANT REVIEW REQUEST</strong><p>' + escapeHTML(claim.appeal_note) + '</p></div>' : "") +
    '<div class="internal-detail"><strong>INTERNAL VERIFICATION DETAIL</strong><small>' + escapeHTML(privateDetail) + "</small></div>" +
    '<div class="list-card-meta"><span>⌖ ' + escapeHTML(report.location) + "</span><span>Submitted " + escapeHTML(humanDateTime(claim.created_at)) + "</span></div>" +
    (claim.status === "disputed" ? '<p class="field-hint">' + escapeHTML(claim.appeal_note
      ? "This is a claimant-requested review of a previous rejection. Review the appeal note and evidence again."
      : "Resolve all competing active claims before approving any one claim.") + '</p>' : "") +
    publicIdentity + checklist + actions + "</article>";
}

async function submitIntake(event) {
  event.preventDefault();
  const form = event.target;
  if (!form.matches("[data-intake-form]")) return;
  const values = new FormData(form);
  const body = {
    confirmed_physical_receipt: values.get("confirmed_physical_receipt") === "on",
    identity_verified_in_person: values.get("identity_verified_in_person") === "on",
    verified_roll_number: String(values.get("verified_roll_number") || "").trim() || null,
    storage_location: String(values.get("storage_location") || "").trim(),
    private_detail: String(values.get("private_detail") || "").trim() || null,
    value_band: values.get("value_band"),
    sensitivity_level: Number(values.get("sensitivity_level"))
  };
  try {
    const result = await api("/api/reports/" + encodeURIComponent(form.dataset.intakeForm) + "/intake", { method: "POST", body });
    showToast("Item received, tagged and stored at " + result.report.storage_location + " · " + result.report.tag_id, false);
    loadOffice();
  } catch (error) { showToast(error.message, true); }
}



async function refreshNotificationBadge() {
  if (!currentUser) return;
  try {
    const data = await api("/api/notifications");
    const badge = $("#notificationNavCount");
    badge.textContent = String(data.unread_count || 0);
    badge.classList.toggle("hidden", !data.unread_count);
  } catch (_) {}
}

async function loadNotifications(silent = false) {
  if (!currentUser) return;
  try {
    const data = await api("/api/notifications");
    $("#notificationNavCount").textContent = String(data.unread_count || 0);
    $("#notificationNavCount").classList.toggle("hidden", !data.unread_count);
    $("#notificationsList").innerHTML = data.notifications.map((item) => {
      const canViewMatches = item.entity_type === "report" && item.entity_id &&
        String(item.title || "").toLowerCase().includes("possible item match");
      const matchButton = canViewMatches
        ? '<button class="button button-primary button-small" type="button" data-notification-matches="' + escapeHTML(item.entity_id) + '">View match details</button>'
        : "";
      return '<article class="notification-card ' + (item.read_at ? "is-read" : "is-unread") + '">' +
        '<div class="notification-mark">' + (item.read_at ? "✓" : "•") + '</div><div class="notification-content"><div class="notification-heading"><strong>' +
        escapeHTML(item.title) + '</strong><span>' + escapeHTML(humanDateTime(item.created_at)) + '</span></div><p>' +
        escapeHTML(item.message) + '</p><div class="notification-actions">' + matchButton + (!item.read_at
          ? '<button class="button button-quiet button-small" type="button" data-notification-read="' + escapeHTML(item.id) + '">Mark read</button>'
          : "") + '</div></div></article>';
    }).join("");
    $("#notificationsEmpty").classList.toggle("hidden", data.notifications.length > 0);
  } catch (error) { if (!silent) showToast(error.message, true); }
}

async function markNotificationRead(notificationId) {
  try {
    await api("/api/notifications/" + encodeURIComponent(notificationId) + "/read", { method: "POST" });
    await loadNotifications();
  } catch (error) { showToast(error.message, true); }
}

async function markAllNotificationsRead() {
  try {
    await api("/api/notifications/read-all", { method: "POST" });
    await loadNotifications();
    showToast("Notifications marked as read.", false);
  } catch (error) { showToast(error.message, true); }
}

async function loadActivity() {
  if (!currentUser || currentUser.role !== "student") return;
  try {
    const data = await api("/api/activity/me");
    const total = Number(data.total_points || 0);
    const next = data.next_milestone;
    const rawProgress = next ? total / next.threshold * 100 : 100;
    const progress = Number.isFinite(rawProgress) ? Math.max(0, Math.min(100, rawProgress)) : 0;
    const nextText = next
      ? (data.points_to_next_milestone + " more points to " + next.tier)
      : "All current recognition milestones earned";
    $("#activityOverview").innerHTML =
      '<div class="activity-points-card"><div><p class="eyebrow">VERIFIED ACTIVITY</p><strong>' + escapeHTML(total) +
      '</strong><span>total points</span></div><div class="points-symbol">✦</div><p class="muted">Points are awarded for contributions verified by the campus office.</p></div>' +
      '<div class="milestone-card"><div class="milestone-heading"><div><p class="eyebrow">NEXT MILESTONE</p><h3>' +
      escapeHTML(next ? next.tier : "Recognition complete") + '</h3></div><span class="count-pill">' +
      escapeHTML(next ? (next.threshold + " pts") : "Complete") + "</span></div><div class=\"progress-track\"><span style=\"width:" +
      progress + '%"></span></div><p class="muted">' + escapeHTML(nextText) + '</p><div class="point-rules"><span>+' +
      escapeHTML(data.rules.verified_intake) + ' <small>verified office intake</small></span><span>+' +
      escapeHTML(data.rules.verified_return) + ' <small>verified return</small></span></div></div>';
    const leaderboard = await api("/api/leaderboard");
    $("#leaderboardParticipantCount").textContent = leaderboard.participant_count + (leaderboard.participant_count === 1 ? " contributor" : " contributors");
    $("#leaderboardSummary").innerHTML = leaderboard.my_rank
      ? '<div class="leaderboard-self"><span>Your current rank</span><strong>#' + escapeHTML(leaderboard.my_rank) + '</strong><small>' + escapeHTML(leaderboard.my_total_points) + ' verified points</small></div>'
      : '<div class="leaderboard-self"><span>Your current rank</span><strong>—</strong><small>Earn points when the office verifies a contribution.</small></div>';
    $("#leaderboardList").innerHTML = leaderboard.leaders.map((leader) =>
      '<div class="leaderboard-row ' + (leader.is_me ? "leaderboard-row-self" : "") + '"><span class="leaderboard-rank">#' +
      escapeHTML(leader.rank) + '</span><span class="leaderboard-name">' + escapeHTML(leader.display_name) + '</span><span class="leaderboard-detail">' +
      escapeHTML(leader.verified_reports) + ' reports</span><strong class="leaderboard-points">' + escapeHTML(leader.total_points) + ' pts</strong></div>'
    ).join("");
    $("#leaderboardEmpty").classList.toggle("hidden", leaderboard.leaders.length > 0);
    $("#certificateList").innerHTML = data.certificates.map((certificate) =>
      '<article class="certificate-card"><div class="certificate-emblem">✧</div><div class="certificate-copy"><span class="item-ref">' +
      escapeHTML(certificate.serial) + "</span><h3>" + escapeHTML(certificate.tier) + '</h3><p class="muted">' +
      escapeHTML(certificate.points_at_issue + " points at issue · " + humanDate(certificate.issued_at)) + '</p></div><button class="button button-primary button-small" type="button" data-certificate-download="' +
      escapeHTML(certificate.id) + '">Download PDF ↗</button></article>'
    ).join("");
    $("#certificateEmpty").classList.toggle("hidden", data.certificates.length > 0);
    $("#activityLedger").innerHTML = data.ledger.map((entry) =>
      '<article class="ledger-row"><div class="ledger-icon">＋</div><div class="ledger-copy"><strong>' +
      escapeHTML(entry.reason) + '</strong><small>' + escapeHTML(humanDateTime(entry.created_at)) +
      (entry.report_id ? " · Verified report recorded" : "") + '</small></div><span class="ledger-points">+' +
      escapeHTML(entry.points) + " pts</span></article>"
    ).join("");
    $("#activityEmpty").classList.toggle("hidden", data.ledger.length > 0);
  } catch (error) { showToast(error.message, true); }
}

function openStorageUpdate(reportId, currentLocation, itemTitle) {
  selectedStorageReportId = reportId;
  $("#storageUpdateSummary").textContent = itemTitle + ". Update this record only after the item has physically been moved.";
  $("#storageUpdateLocation").value = currentLocation || "";
  $("#storageUpdateNote").value = "";
  $("#storageUpdateError").textContent = "";
  $("#saveStorageUpdateButton").disabled = false;
  $("#storageUpdateDialog").showModal();
}

async function submitStorageLocation(event) {
  event.preventDefault();
  if (!selectedStorageReportId) return;
  const storageLocation = $("#storageUpdateLocation").value.trim();
  if (storageLocation.length < 4) {
    $("#storageUpdateError").textContent = "Enter a specific room, cabinet, shelf or storage area.";
    $("#storageUpdateLocation").focus();
    return;
  }
  $("#storageUpdateError").textContent = "";
  $("#saveStorageUpdateButton").disabled = true;
  try {
    const result = await api("/api/reports/" + encodeURIComponent(selectedStorageReportId) + "/storage", {
      method: "POST",
      body: {
        storage_location: storageLocation,
        note: $("#storageUpdateNote").value.trim() || null
      }
    });
    $("#storageUpdateDialog").close();
    selectedStorageReportId = null;
    showToast(result.message, false);
    await loadOffice();
  } catch (error) {
    $("#storageUpdateError").textContent = error.message;
  } finally {
    $("#saveStorageUpdateButton").disabled = false;
  }
}

async function openCloseReport(reportId, reportType) {
  selectedCloseReportId = reportId;
  selectedCloseReportType = reportType;
  $("#closeReportError").textContent = "";
  $("#closeReportNote").value = "";
  const isFound = reportType === "found";
  $("#closeReportDialogTitle").textContent = isFound ? "Withdraw found report" : "Close lost report";
  $("#closeReportDescription").textContent = isFound
    ? "Withdraw this report only if you have not yet handed the physical item to the campus office. Once staff accept it and assign a tag, contact the office instead."
    : "Close your search if you recovered the item elsewhere, no longer need to search, or submitted a duplicate. Closed reports stop generating match suggestions.";
  $("#confirmCloseReportButton").textContent = isFound ? "Withdraw report" : "Close report";
  $("#closeReportReason").innerHTML = isFound
    ? '<option value="found_report_withdrawn">I cannot deliver the item to the office</option>'
    : '<option value="recovered_elsewhere">I recovered the item elsewhere</option><option value="no_longer_searching">I no longer need to search</option><option value="duplicate">This is a duplicate report</option>';
  $("#closeReportReason").value = isFound ? "found_report_withdrawn" : "no_longer_searching";
  $("#closeReportDialog").showModal();
}

async function submitCloseReport(event) {
  event.preventDefault();
  if (!selectedCloseReportId) return;
  try {
    const result = await api("/api/reports/" + encodeURIComponent(selectedCloseReportId) + "/close", {
      method: "POST",
      body: { reason: $("#closeReportReason").value, note: $("#closeReportNote").value.trim() || null }
    });
    $("#closeReportDialog").close();
    selectedCloseReportId = null;
    selectedCloseReportType = null;
    showToast(result.message, false);
    await loadMyReports();
  } catch (error) { $("#closeReportError").textContent = error.message; }
}

async function submitClaimDispute(claimId) {
  const textarea = $('[data-dispute-reason="' + CSS.escape(claimId) + '"]');
  const reason = textarea ? textarea.value.trim() : "";
  if (reason.length < 20) {
    showToast("Please explain why the decision should be reviewed (at least 20 characters).", true);
    if (textarea) textarea.focus();
    return;
  }
  try {
    const result = await api("/api/claims/" + encodeURIComponent(claimId) + "/dispute", {
      method: "POST", body: { reason }
    });
    showToast(result.message, false);
    await loadMyClaims();
  } catch (error) { showToast(error.message, true); }
}

function openHandoverDialog(claimId, itemTitle, rollNumber = "") {
  selectedHandoverClaimId = claimId;
  selectedHandoverRollNumber = rollNumber || null;
  $("#handoverSummary").textContent = "Before releasing " + itemTitle + ", read the physical label and compare it with the Tag ID in the office record.";
  $("#handoverTag").value = "";
  $("#handoverVerifiedRoll").value = "";
  $("#handoverRollVerificationGroup").classList.toggle("hidden", !selectedHandoverRollNumber);
  $("#handoverIdentityChecked").checked = false;
  $("#handoverPhysicalChecked").checked = false;
  $("#handoverNote").value = "";
  $("#handoverError").textContent = "";
  $("#confirmHandoverButton").disabled = false;
  $("#handoverDialog").showModal();
  $("#handoverTag").focus();
}

async function submitHandover(event) {
  event.preventDefault();
  if (!selectedHandoverClaimId) return;
  const tagId = $("#handoverTag").value.trim();
  if (tagId.length < 4) {
    $("#handoverError").textContent = "Enter the exact physical Tag ID from the item label.";
    $("#handoverTag").focus();
    return;
  }
  if (!$("#handoverIdentityChecked").checked || !$("#handoverPhysicalChecked").checked) {
    $("#handoverError").textContent = "Confirm both the identity check and actual physical handover.";
    return;
  }
  if (selectedHandoverRollNumber && $("#handoverVerifiedRoll").value.trim().toUpperCase() !== selectedHandoverRollNumber.toUpperCase()) {
    $("#handoverError").textContent = "The verified college roll number must match the public claim record.";
    $("#handoverVerifiedRoll").focus();
    return;
  }
  $("#handoverError").textContent = "";
  $("#confirmHandoverButton").disabled = true;
  try {
    const result = await api("/api/claims/" + encodeURIComponent(selectedHandoverClaimId) + "/handover", {
      method: "POST",
      body: {
        tag_id: tagId,
        confirmed_physical_handover: $("#handoverPhysicalChecked").checked,
        claimant_identity_checked: $("#handoverIdentityChecked").checked,
        verified_roll_number: $("#handoverVerifiedRoll").value.trim() || null,
        note: $("#handoverNote").value.trim() || null
      }
    });
    $("#handoverDialog").close();
    selectedHandoverClaimId = null;
    selectedHandoverRollNumber = null;
    showToast(result.message, false);
    await loadOffice();
  } catch (error) {
    $("#handoverError").textContent = error.message;
  } finally {
    $("#confirmHandoverButton").disabled = false;
  }
}


function openDecisionConfirmation(claimId, action) {
  if (action === "approve") {
    const card = $('[data-claim-card="' + CSS.escape(claimId) + '"]');
    const level = Number(card && card.dataset.verificationLevel || 3);
    const minimum = Number(card && card.dataset.minimumChecks || ({1:2,2:3,3:4,4:4})[level] || 4);
    const checked = card ? $$('[data-verification-check]:checked', card).map((input) => input.value) : [];
    let reason = "";
    if (checked.length < minimum) reason = "Select at least " + minimum + " distinct verification checks before verifying this claim.";
    else if (!checked.includes("claimant_identity")) reason = "Confirm the claimant's identity before verifying this claim.";
    else if (card && card.dataset.publicClaim === "true" &&
      (!card.querySelector("[data-identity-verified]")?.checked ||
       card.querySelector("[data-verified-roll]")?.value.trim().toUpperCase() !== (card.dataset.expectedRoll || "").toUpperCase()))
      reason = "Physically verify the claimant's college ID and enter the matching roll number before approving this public claim.";
    else if (level >= 4 && !checked.includes("authorised_record")) reason = "Restricted items require the authorised-record / custodian check.";
    if (reason) {
      let message = card && card.querySelector(".field-error-note");
      if (!message && card) { message = document.createElement("p"); message.className = "field-error-note"; message.setAttribute("role","alert"); card.querySelector(".verification-checklist").appendChild(message); }
      if (message) message.textContent = reason;
      if (card) { card.scrollIntoView({behavior:"smooth",block:"center"}); card.querySelector(".verification-checklist").focus({preventScroll:true}); }
      showToast(reason, true); return;
    }
    const oldMessage=card && card.querySelector(".field-error-note"); if(oldMessage) oldMessage.remove();
  }
  const actions = {
    approve: {
      title: "Verify claim",
      button: "Verify claim",
      message: "Approve this claim only after reviewing the private evidence and completing every required verification check. The item will move to the physical handover queue."
    },
    reject: {
      title: "Reject claim",
      button: "Reject claim",
      message: "Reject this claim only after reviewing the available evidence. The claimant will be notified and may request one review."
    },
    request_more_evidence: {
      title: "Request more evidence",
      button: "Request evidence",
      message: "Ask the claimant to supply additional ownership evidence before the office makes a final decision."
    },
    mark_disputed: {
      title: "Mark claim as disputed",
      button: "Mark disputed",
      message: "Place this claim on hold. Competing claims or unresolved evidence must be reviewed before any item can be released."
    }
  };
  const actionInfo = actions[action];
  if (!actionInfo) {
    showToast("Unknown claim decision.", true);
    return;
  }
  selectedDecisionClaimId = claimId;
  selectedDecisionAction = action;
  $("#decisionConfirmTitle").textContent = actionInfo.title;
  $("#decisionConfirmMessage").textContent = actionInfo.message;
  $("#confirmDecisionButton").textContent = actionInfo.button;
  $("#confirmDecisionButton").className = "button " + (action === "reject" ? "button-danger" : "button-primary");
  $("#decisionConfirmError").textContent = "";
  $("#confirmDecisionButton").disabled = false;
  $("#decisionConfirmDialog").showModal();
}

async function submitDecision(event) {
  event.preventDefault();
  if (!selectedDecisionClaimId || !selectedDecisionAction || claimDecisionSubmitting) return;
  const claimId = selectedDecisionClaimId;
  const action = selectedDecisionAction;
  const noteInput = $('[data-note-for="' + CSS.escape(claimId) + '"]');
  const note = noteInput ? noteInput.value.trim() : "";
  const card = $('[data-claim-card="' + CSS.escape(claimId) + '"]');
  const verificationChecks = action === "approve" && card
    ? $$('[data-verification-check]:checked', card).map((input) => input.value)
    : [];
  claimDecisionSubmitting = true;
  $("#confirmDecisionButton").disabled = true;
  $("#decisionConfirmError").textContent = "";
  try {
    const result = await api("/api/claims/" + encodeURIComponent(claimId) + "/decision", {
      method: "POST",
      body: {
        action, note: note || null, verification_checks: verificationChecks,
        identity_verified_in_person: Boolean(card && card.querySelector("[data-identity-verified]")?.checked),
        verified_roll_number: card && card.querySelector("[data-verified-roll]")?.value.trim() || null
      }
    });
    $("#decisionConfirmDialog").close();
    selectedDecisionClaimId = null;
    selectedDecisionAction = null;
    showToast(result.message, false);
    await loadOffice();
  } catch (error) {
    $("#decisionConfirmError").textContent = error.message;
  } finally {
    claimDecisionSubmitting = false;
    $("#confirmDecisionButton").disabled = false;
  }
}

function placeFinnIn(selector) {
  const dock = $("#finnDock");
  const slot = selector ? $(selector) : null;
  if (dock && slot) slot.appendChild(dock);
  else if (dock) document.body.appendChild(dock);
}

function setPublicNavActive(destination) {
  const nav = $("#publicNav");
  if (!nav) return;
  nav.querySelectorAll("[data-public-destination]").forEach(button => {
    const active = button.dataset.publicDestination === destination;
    button.classList.toggle("active", active);
    if (active) button.setAttribute("aria-current", "page");
    else button.removeAttribute("aria-current");
  });
}

function showPublicHome() {
  setPublicNavActive("home");
  stopNotificationPolling();
  setFinnMessage("Welcome back to campus, detective. What are we looking for today?", false);
  currentUser = null;
  $("#loginView").classList.remove("hidden");
  $("#loginView").classList.remove("office-access-open");
  $("#appView").classList.add("hidden");
  $("#officeLoginPanel").classList.add("hidden");
  $("#publicHomeContent").classList.remove("hidden");
  placeFinnIn("#publicHomeContent [data-finn-slot]");
  ["publicLostPage","publicFoundPage","publicBrowsePage","publicTrackPage"].forEach(id => $("#"+id).classList.add("hidden"));
  window.scrollTo({top:0,behavior:"instant"});
}
function showPublicDestination(type) {
  setPublicNavActive(type);
  setFinnMessage(type === "browse" ? "Let’s search both open Lost reports and items the office has received." : type === "track" ? "Enter your case reference and roll number. I’ll check for private access saved by this browser." : type === "found" ? "Tell us what you found. The office will record it before it appears in search." : "Let’s make a clear Lost report so we can find useful matches.", false);
  $("#loginView").classList.remove("hidden");
  $("#appView").classList.add("hidden");
  $("#officeLoginPanel").classList.add("hidden");
  $("#publicHomeContent").classList.add("hidden");
  const destination = type === "browse" ? "publicBrowsePage" : type === "track" ? "publicTrackPage" : type === "found" ? "publicFoundPage" : "publicLostPage";
  ["publicLostPage","publicFoundPage","publicBrowsePage","publicTrackPage"].forEach(id => $("#"+id).classList.toggle("hidden",id !== destination));
  placeFinnIn("#"+destination+" [data-finn-slot]");
  if (type === "browse") {
    $("#publicBrowseEmpty").textContent = "Loading campus reports…";
    $("#publicBrowseEmpty").classList.remove("hidden");
    loadPublicFound();
  }
  if (type === "lost" || type === "found") {
    const reportPage = $("#" + destination);
    const hiddenType = reportPage.querySelector("input[type=hidden]");
    if (hiddenType) hiddenType.value = type;
    const title = reportPage.querySelector(".public-title");
    const eyebrow = reportPage.querySelector(".eyebrow");
    const lede = reportPage.querySelector(".public-lede");
    const submit = reportPage.querySelector("form button[type=submit]");
    if (type === "found") {
      eyebrow.textContent = "PUBLIC REPORT · FOUND";
      title.innerHTML = 'You found it.<br><span>Let’s reunite it.</span>';
      lede.textContent = "Tell us what you found. The campus office will verify your college ID when you hand in the item.";
      submit.textContent = "Submit found report ↗";
      reportPage.querySelector("#publicDescriptionFound").placeholder = "Describe the item as you found it: type, size, material, condition and visible details. Do not guess who owns it.";
      reportPage.querySelector("#publicFeaturesFound").placeholder = "Visible exterior details only. Keep contents, serial numbers and hidden identifying marks private.";
      reportPage.querySelector("#publicAreaFound").placeholder = "e.g. Outside Lab 3, under a library desk, near the stairs";
    } else {
      eyebrow.textContent = "PUBLIC REPORT · LOST";
      title.innerHTML = 'Let’s find<br><span>what’s missing.</span>';
      lede.textContent = "Submit a report using your college roll number. No student account or password is needed.";
      submit.textContent = "Submit lost report ↗";
      reportPage.querySelector("#publicDescription").placeholder = "Describe the item you lost and the details that could help you recognise it. Keep unique ownership clues private.";
      reportPage.querySelector("#publicFeatures").placeholder = "Colour patterns, stickers, scratches, logos, case or accessories…";
      reportPage.querySelector("#publicArea").placeholder = "e.g. Library reading room, canteen counter, bus bay";
    }
  }
  if (type === "browse") loadPublicFound();
  window.scrollTo({top:0,behavior:"smooth"});
}
async function publicApi(path, options) {
  const opts = Object.assign({method:"GET",credentials:"omit",headers:{}},options || {});
  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort(), 25000);
  if (opts.signal && typeof AbortSignal.any === "function") {
    opts.signal = AbortSignal.any([opts.signal, controller.signal]);
  } else {
    opts.signal = controller.signal;
  }
  let response;
  try {
    response = await fetch(API_BASE_URL + path,opts);
  } catch (error) {
    if (error && error.name === "AbortError") {
      throw new Error("The LostLink server took too long to respond. It may be waking from a cold start; please retry.");
    }
    throw new Error("LostLink API is unreachable. Check the backend deployment and API origin.");
  } finally {
    window.clearTimeout(timeoutId);
  }
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(explainError(data,"Request failed ("+response.status+")."));
  return data;
}
async function loadPublicFound() {
  const q = $("#publicBrowseQuery").value.trim();
  const category = $("#publicBrowseCategory").value;
  const params = new URLSearchParams();
  if (q) params.set("q",q);
  if (category) params.set("category",category);
  try {
    const data = await publicApi("/api/public/search"+(params.size ? "?"+params.toString() : ""));
    const reports = Array.isArray(data.reports) ? data.reports : [];
    $("#publicBrowseResults").innerHTML = reports.map(item => {
      const isFound = String(item.report_type || "").toLowerCase() === "found";
      const canClaim = isFound && String(item.status || "").toLowerCase() === "available";
      return '<article class="list-card public-browse-card"><div class="list-card-head"><div><span class="eyebrow">'+(isFound ? "FOUND ITEM" : "LOST REPORT")+'</span><h3>'+escapeHTML(item.title)+'</h3><p>'+escapeHTML(categoryLabel(item.category))+' · '+escapeHTML(item.public_ref || item.reference)+'</p></div><span class="status-pill">'+escapeHTML(statusLabel(item.status))+'</span></div><p class="field-hint">'+escapeHTML(item.location_area || item.location_block || "Campus location")+'</p>'+(canClaim ? '<div class="public-browse-actions"><button class="button button-liquid public-claim-action" type="button" data-public-claim="'+escapeHTML(item.id)+'" data-public-ref="'+escapeHTML(item.public_ref || item.reference || '')+'">Claim this item <span aria-hidden="true">→</span></button><span class="public-claim-hint">Submit ownership evidence for office review</span></div>' : (isFound ? '<p class="field-hint">This item is not yet available to claim.</p>' : ''))+'</article>';
    }).join("");
    $("#publicBrowseEmpty").textContent = reports.length ? "No claimable Found items yet. Found items appear here after the campus office receives and lists them." : "No public reports match that search yet.";
    $("#publicBrowseEmpty").classList.toggle("hidden", reports.length > 0);
  } catch(error) {
    $("#publicBrowseResults").innerHTML = "";
    $("#publicBrowseEmpty").classList.remove("hidden");
    $("#publicBrowseEmpty").textContent = error.message;
  }
}
function openPublicOfficeSignIn() {
  setPublicNavActive("office");
  setFinnMessage("Welcome to the campus desk. This sign-in is for authorised office staff.", false);
  $("#loginView").classList.add("office-access-open");
  $("#loginPanelKicker").textContent = "OFFICE STAFF ACCESS";
  $("#loginPanelTitle").textContent = "Office staff sign in";
  $("#loginPanelCopy").textContent = "Authorised campus staff only. Office access is restricted to approved staff email addresses.";
  $("#loginError").textContent = "";
  $("#loginForm").reset();
  $("#publicHomeContent").classList.add("hidden");
  ["publicLostPage","publicFoundPage","publicBrowsePage","publicTrackPage"].forEach(id => $("#"+id).classList.add("hidden"));
  placeFinnIn("#officeLoginPanel [data-finn-slot]");
  $("#officeLoginPanel").classList.remove("hidden");
  $("#loginEmail").focus();
}
// One document-level handler owns all public navigation actions. This avoids
// losing click behaviour when a public panel or navigation item is replaced.
document.addEventListener("click", event => {
  const button = event.target.closest("[data-public-destination]");
  if (!button) return;
  event.preventDefault();
  const destination = button.dataset.publicDestination;
  if (destination === "home") showPublicHome();
  else if (destination === "office") openPublicOfficeSignIn();
  else showPublicDestination(destination);
});
$("#publicBrowseButton").addEventListener("click",() => showPublicDestination("browse"));
$("#publicTrackButton").addEventListener("click",() => showPublicDestination("track"));
$("#publicOfficeButton").addEventListener("click",openPublicOfficeSignIn);
$("#closeOfficeAccess").addEventListener("click",showPublicHome);
// Delegate public actions from the document so they continue working if
// public panels are re-rendered or their buttons are replaced.
document.addEventListener("click", event => {
  const reportButton = event.target.closest("[data-public-report]");
  if (reportButton) {
    event.preventDefault();
    showPublicDestination(reportButton.dataset.publicReport);
    (reportButton.dataset.publicReport === "found" ? $("#publicFoundPage .public-title") : $("#publicLostPage .public-title")).scrollIntoView({behavior:"smooth",block:"start"});
    return;
  }
  const homeButton = event.target.closest("[data-public-home]");
  if (homeButton) {
    event.preventDefault();
    showPublicHome();
  }
});
$("#publicBrowseForm").addEventListener("submit",event => {event.preventDefault();loadPublicFound();});
const publicAccessMemory = new Map();
function buildPublicTrackingUrl(reference, roll, secret) {
  const url = new URL(window.location.href);
  url.search = "";
  url.searchParams.set("track", reference);
  url.searchParams.set("roll", String(roll).trim().toUpperCase());
  url.hash = "secret=" + encodeURIComponent(secret);
  return url.toString();
}
function parsePublicTrackingUrl(value) {
  try {
    const url = new URL(String(value || "").trim(), window.location.href);
    if (url.origin !== window.location.origin) return null;
    const reference = url.searchParams.get("track");
    const roll = url.searchParams.get("roll");
    const secret = new URLSearchParams(url.hash.replace(/^#/, "")).get("secret");
    if (!reference || !roll || !secret || secret.length < 20) return null;
    return {reference, roll: roll.trim().toUpperCase(), secret};
  } catch (_) { return null; }
}
function privateTrackingReceiptMarkup(message, trackingUrl) {
  return '<p>' + escapeHTML(message) + '</p><p><a class="button button-liquid button-small" href="' +
    escapeHTML(trackingUrl) + '">Open private tracking link ↗</a></p>' +
    '<p class="field-hint">Keep this link private. Anyone who has it can view this case status.</p>';
}
function storePublicAccess(reference, roll, secret) {
  if (!reference || !roll || !secret) return;
  const access = {roll: String(roll).trim().toUpperCase(), secret: String(secret)};
  publicAccessMemory.set(reference, access);
  try { sessionStorage.setItem("lostlink:private-access:" + reference, JSON.stringify(access)); } catch (_) {}
  const linkField = $("#publicTrackLink");
  if (linkField) linkField.value = buildPublicTrackingUrl(reference, access.roll, access.secret);
}
function getPublicAccess(reference, roll, suppliedSecret) {
  const normalizedRoll = String(roll || "").trim().toUpperCase();
  let secret = String(suppliedSecret || "").trim();
  if (!secret) {
    let access = publicAccessMemory.get(reference) || null;
    if (!access) {
      try { const raw = sessionStorage.getItem("lostlink:private-access:" + reference); access = raw ? JSON.parse(raw) : null; }
      catch (_) { access = null; }
    }
    if (access && access.roll === normalizedRoll) secret = String(access.secret || "");
  }
  if (!normalizedRoll || !secret) return null;
  return {"X-LostLink-Roll-Number": normalizedRoll, "X-LostLink-Tracking-Secret": secret};
}
function publicMatchClaimButton(report) {
  if (!report || report.report_type !== "found" || report.status !== "available") return "";
  return '<div class="public-browse-actions"><button class="button button-liquid public-claim-action" type="button" data-public-claim="' + escapeHTML(report.id) + '" data-public-ref="' + escapeHTML(report.public_ref || report.reference || "") + '">Claim this item <span aria-hidden="true">→</span></button></div>';
}
function openPublicClaimDialog(report) {
  if (!report || !report.id || report.report_type !== "found" || report.status !== "available") {
    showToast("This Found item is no longer available for claims. Refresh the list.", true); return;
  }
  selectedPublicFoundId = report.id;
  $("#publicClaimItemSummary").innerHTML = "<strong>" + escapeHTML(report.title || "Found item") + " · " + escapeHTML(report.public_ref || "") + "</strong><small>" + escapeHTML(categoryLabel(report.category)) + " · " + escapeHTML(report.location_area || report.location || "Campus") + "</small>";
  $("#publicClaimError").textContent = "";
  $("#publicClaimForm").reset();
  const dialog = $("#publicClaimDialog");
  if (!dialog.open) dialog.showModal();
}
async function openPublicClaimById(reportId, publicRef) {
  try {
    if (!reportId) throw new Error("This Found item link is incomplete. Refresh Browse and try again.");
    const data = await publicApi("/api/public/found/" + encodeURIComponent(reportId));
    const report = data.report;
    if (!report || report.id !== reportId || report.report_type !== "found" || report.status !== "available") {
      throw new Error("This Found item is no longer available for claims. Refresh Browse.");
    }
    openPublicClaimDialog(report);
  } catch (error) { showToast(error.message, true); }
}

let selectedPublicFoundId = null;
document.addEventListener("click", event => {
  const button = event.target.closest("[data-public-claim]");
  if (!button || button.disabled) return;
  event.preventDefault();
  event.stopPropagation();
  void openPublicClaimById(button.dataset.publicClaim, button.dataset.publicRef);
});
$("#publicClaimClose").addEventListener("click", () => $("#publicClaimDialog").close());
$("#publicClaimCancel").addEventListener("click", () => $("#publicClaimDialog").close());
$("#publicClaimForm").addEventListener("submit", async event => {
  event.preventDefault();
  if (!selectedPublicFoundId || claimSubmitting) return;
  const roll = $("#publicClaimRoll").value.trim().toUpperCase();
  const contactPhone = $("#publicClaimPhone").value.trim();
  const evidence = $("#publicClaimEvidence").value.trim();
  const evidenceTypes = $$('input[name="publicClaimEvidenceType"]:checked').map(input => input.value);
  const errorNode = $("#publicClaimError");
  errorNode.textContent = "";
  if (evidence.length < 20) { errorNode.textContent = "Please provide at least 20 characters explaining how you can verify ownership."; return; }
  if (!evidenceTypes.length) { errorNode.textContent = "Select at least one type of supporting evidence."; return; }
  const button = $("#publicClaimSubmit");
  claimSubmitting = true;
  button.disabled = true;
  try {
    const lostReportReference = $("#publicClaimLostReference").value.trim();
    const result = await publicApi("/api/public/found/" + encodeURIComponent(selectedPublicFoundId) + "/claims", {
      method: "POST",
      headers: {"Content-Type":"application/json"},
      body: JSON.stringify({roll_number:roll,contact_phone:contactPhone || null,evidence,evidence_types:evidenceTypes,lost_report_reference:lostReportReference || null})
    });
    storePublicAccess(result.claim.reference, roll, result.tracking_secret);
    const claimTrackingUrl = $("#publicTrackLink").value;
    $("#publicTrackResult").innerHTML = privateTrackingReceiptMarkup(
      "Claim submitted. Your private tracking link is ready.", claimTrackingUrl
    );
    $("#publicClaimDialog").close();
    selectedPublicFoundId = null;
    showPublicDestination("track");
  } catch(error) { errorNode.textContent = error.message; }
  finally { claimSubmitting = false; button.disabled = false; }
});
async function requestPublicCategorySuggestion(button) {
  const form = button.closest("form");
  if (!form) return;
  const found = form.id === "publicFoundReportForm";
  const suffix = found ? "Found" : "";
  const field = (id) => form.querySelector("#" + id + suffix);
  const output = form.querySelector(found ? "#publicCategorySuggestionFound" : "#publicCategorySuggestion");
  const payload = {
    title: field("publicTitle").value.trim(),
    description: field("publicDescription").value.trim(),
    brand: field("publicBrand").value.trim() || null,
    primary_color: field("publicColor").value.trim() || null,
    visible_features: field("publicFeatures").value.trim() || null
  };
  if (payload.title.length < 4 || payload.description.length < 10) {
    output.textContent = "Enter an item name (at least 4 characters) and description (at least 10 characters) first.";
    (payload.title.length < 4 ? field("publicTitle") : field("publicDescription")).focus();
    return;
  }
  button.disabled = true;
  button.textContent = "Analysing…";
  output.textContent = "Checking item details…";
  try {
    const result = await publicApi("/api/public/category-suggestion", {
      method: "POST", headers: {"Content-Type":"application/json"}, body: JSON.stringify(payload)
    });
    const suggestion = result.suggestion || {};
    if (suggestion.status !== "suggested" || !suggestion.category) {
      output.textContent = "No confident category suggestion. Please choose one manually.";
      return;
    }
    const alternatives = (suggestion.alternatives || []).slice(0, 3);
    output.replaceChildren();
    const heading = document.createElement("span");
    heading.textContent = "Suggested: " + (suggestion.label || categoryLabel(suggestion.category));
    output.append(heading);
    const actions = document.createElement("span");
    actions.className = "public-ai-alternatives";
    alternatives.forEach(item => {
      const option = document.createElement("button");
      option.type = "button";
      option.className = "ai-alternative-button";
      option.textContent = item.label || categoryLabel(item.category);
      option.addEventListener("click", () => {
        form.querySelector(found ? "#publicCategoryFound" : "#publicCategory").value = item.category;
        output.textContent = (item.label || categoryLabel(item.category)) + " selected. Review it before submitting.";
      });
      actions.append(option);
    });
    output.append(actions);
    const note = document.createElement("span");
    note.textContent = "AI suggestions are advisory; select a category to apply it.";
    output.append(note);
  } catch (error) {
    output.textContent = error.message || "AI suggestion is unavailable. Choose a category manually.";
  } finally {
    button.disabled = false;
    button.textContent = "✦ Suggest with AI";
  }
}
document.addEventListener("click", event => {
  const button = event.target.closest("[data-public-ai-category]");
  if (button) void requestPublicCategorySuggestion(button);
});

function publicReportField(form, id) {
  return form.querySelector("#" + id + (form.id === "publicFoundReportForm" ? "Found" : ""));
}
async function submitPublicReport(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const field = (id) => publicReportField(form, id);
  const type = field("publicReportType").value;
  const body = {
    report_type: type,
    roll_number: field("publicRollNumber").value.trim(),
    contact_phone: field("publicContactPhone").value.trim() || null,
    contact_email: field("publicContactEmail").value.trim().toLowerCase() || null,
    title: field("publicTitle").value.trim(),
    category: field("publicCategory").value,
    description: field("publicDescription").value.trim(),
    brand: field("publicBrand").value.trim() || null,
    primary_color: field("publicColor").value.trim() || null,
    visible_features: field("publicFeatures").value.trim() || null,
    location_block: field("publicBlock").value || null,
    location_floor: field("publicFloor").value || null,
    location_room: field("publicRoom").value.trim() || null,
    location_area: field("publicArea").value.trim() || null,
    occurred_at: field("publicDate").value || null,
    private_detail: type === "lost" ? field("publicPrivateDetail").value.trim() || null : null,
    item_condition: type === "found" ? field("publicItemCondition").value || null : null,
    handover_at: type === "found" ? field("publicHandoverAt").value || null : null,
    handover_recipient: type === "found" ? field("publicHandoverRecipient").value.trim() || null : null,
    handover_note: type === "found" ? field("publicHandoverNote").value.trim() || null : null,
    image_ai_consent: Boolean(field("publicImageAiConsent")?.checked)
  };
  const errorNode = field("publicReportError");
  const button = form.querySelector('button[type="submit"]');
  errorNode.textContent = "";
  if (!body.location_block && !body.location_area) {
    errorNode.textContent = type === "found"
      ? "Choose the building or exact area where you found the item."
      : "Choose a campus building or enter the area where you last had the item.";
    return;
  }
  if (body.location_block === "Other / Not listed" && !body.location_area) {
    errorNode.textContent = "Add a short location detail when you choose Other / Not listed.";
    field("publicArea").focus();
    return;
  }
  if (!button || button.disabled) return;
  button.disabled = true;
  try {
    const result = await publicApi("/api/public/reports", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(body)
    });
    storePublicAccess(result.case.reference, body.roll_number, result.tracking_secret);
    const reportTrackingUrl = $("#publicTrackLink").value;
    let photoStatus = "";
    const photo = field("publicImage").files && field("publicImage").files[0];
    if (photo) {
      const photoBody = new FormData();
      photoBody.append("file", photo);
      try {
        await publicApi("/api/public/reports/" + encodeURIComponent(result.case.reference) + "/image", {
          method: "POST",
          headers: getPublicAccess(result.case.reference, body.roll_number),
          body: photoBody
        });
        photoStatus = " Your photo was saved privately for office review.";
      } catch (photoError) {
        photoStatus = " The report was saved, but its photo could not be uploaded: " + photoError.message;
      }
    }
    const matchCards = (result.matches || []).map(match => {
      const item = match.report;
      return '<article class="list-card"><div class="list-card-head"><div><h3>' + escapeHTML(item.title) + '</h3><p>' +
        escapeHTML(item.public_ref || item.reference) + ' · ' + escapeHTML(categoryLabel(item.category)) +
        '</p></div><span class="status-pill">' + escapeHTML(match.strength || "Possible match") + '</span></div><p>' +
        escapeHTML(item.description) + '</p><p class="field-hint">' + escapeHTML((match.reasons || []).join(" · ")) + '</p>' + publicMatchClaimButton(item) + '</article>';
    }).join("");
    $("#publicTrackResult").innerHTML = privateTrackingReceiptMarkup(
      "Report submitted. Reference: " + result.case.reference + ".", reportTrackingUrl
    ) + (matchCards ? '<h3>Possible matches</h3>' + matchCards : '<p class="field-hint">No possible matches are available yet. You can check again later.</p>') +
      (photoStatus ? '<p class="field-hint">' + escapeHTML(photoStatus) + '</p>' : '');
    form.reset();
    showPublicDestination("track");
    setFinnMessage("Case opened! Your private access is saved in this browser.", true);
    showToast("Report submitted successfully.", false);
  } catch (error) {
    errorNode.textContent = error.message;
  } finally {
    button.disabled = false;
  }
}
document.querySelectorAll("#publicReportForm, #publicFoundReportForm").forEach((form) => {
  form.addEventListener("submit", submitPublicReport);
});
let lastPublicTracking = null;
async function refreshPublicMatches(reference, credentials, target) {
  try {
    const data = await publicApi("/api/public/reports/" + encodeURIComponent(reference) + "/matches", {headers:credentials});
    const matches = data.matches || [];
    target.innerHTML = '<h3>Possible matches</h3>' + (matches.length ? matches.map(match => {
      const report = match.report || {};
      const reasons = Array.isArray(match.reasons) ? match.reasons : [];
      return '<article class="list-card"><strong>' + escapeHTML(report.title || "Possible item") + '</strong><p>' +
        escapeHTML(report.public_ref || report.reference || "") + ' · ' + escapeHTML(report.location_area || report.location || "Campus") +
        '</p><span class="status-pill">' + escapeHTML(match.strength || "Suggested match") + '</span>' +
        (reasons.length ? '<p class="field-hint">' + escapeHTML(reasons.join(" · ")) + '</p>' : '') + publicMatchClaimButton(report) + '</article>';
    }).join("") : '<p class="field-hint">No possible matches are available yet. Try refreshing later.</p>');
  } catch(error) { target.innerHTML = '<p class="form-error">' + escapeHTML(error.message) + '</p>'; }
}
$("#copyPublicTrackingLink").addEventListener("click", async () => {
  const field = $("#publicTrackLink");
  const value = field.value.trim();
  if (!value) { showToast("Paste or open the private tracking link from your receipt first.", true); return; }
  try { await navigator.clipboard.writeText(value); showToast("Private tracking link copied.", false); }
  catch (_) { field.focus(); field.select(); showToast("Select and copy the private tracking link.", false); }
});
$("#publicTrackForm").addEventListener("submit", async event => {
  event.preventDefault();
  const resultNode = $("#publicTrackResult");
  const access = parsePublicTrackingUrl($("#publicTrackLink").value);
  if (!access) {
    lastPublicTracking = null;
    resultNode.textContent = "Paste the private LostLink tracking link from your submission receipt. Roll number alone cannot unlock private case details.";
    return;
  }
  const {reference, roll, secret} = access;
  resultNode.textContent = "Checking private case access…";
  const credentials = getPublicAccess(reference, roll, secret);
  if (!credentials) {
    lastPublicTracking = null;
    resultNode.textContent = "This private tracking link is incomplete. Open the original link from your receipt.";
    return;
  }
  storePublicAccess(reference, roll, secret);
  try {
    const data = await publicApi("/api/public/track/" + encodeURIComponent(reference), {headers:credentials});
    lastPublicTracking = {reference,roll,data};
    const record = data.case || data.claim || {};
    const item = data.case || data.item || {};
    const isCase = Boolean(data.case);
    const events = (data.events || []).map(entry => '<article class="list-card"><strong>' + escapeHTML(entry.title) + '</strong><p>' + escapeHTML(entry.message) + '</p><small>' + escapeHTML(humanDateTime(entry.created_at)) + '</small></article>').join("");
    const actions = [];
    if (isCase && item.report_type === "lost" && item.status === "open") {
      actions.push('<button class="button button-quiet button-small" type="button" data-public-refresh-matches>Refresh matches</button>');
      actions.push('<button class="button button-quiet button-small" type="button" data-public-close-case>Close report</button>');
    }
    if (!isCase && record.status === "needs_more_evidence") {
      actions.push('<button class="button button-liquid button-small" type="button" data-public-add-evidence>Submit requested evidence</button>');
    }
    resultNode.innerHTML = '<section class="track-summary"><p><strong>Reference ' + escapeHTML(record.reference || reference) + '</strong> · Status: ' + escapeHTML(statusLabel(record.status || "unknown")) + '</p><p>' + escapeHTML(record.title || item.title || "Claim") + '</p>' +
      (typeof data.case_points === "number" ? '<p class="field-hint">Points linked to this case: ' + data.case_points + '</p>' : '') +
      '<div class="form-actions">' + actions.join("") + '</div></section>' +
      (events ? '<h3>Case updates</h3>' + events : '<p class="field-hint">No additional updates have been recorded yet.</p>') +
      (isCase && item.report_type === "lost" ? '<div id="publicTrackMatches" class="track-matches"></div>' : '');
    if (isCase && item.report_type === "lost") await refreshPublicMatches(reference, credentials, $("#publicTrackMatches"));
  } catch(error) { lastPublicTracking = null; resultNode.textContent = error.message; }
});
$("#publicTrackResult").addEventListener("click", async event => {
  const state = lastPublicTracking;
  if (!state) return;
  const credentials = getPublicAccess(state.reference, state.roll);
  if (!credentials) { lastPublicTracking = null; $("#publicTrackResult").textContent = "Private access is no longer available in this browser."; return; }
  if (event.target.closest("[data-public-refresh-matches]")) {
    await refreshPublicMatches(state.reference, credentials, $("#publicTrackMatches"));
  } else if (event.target.closest("[data-public-close-case]")) {
    if (!confirm("Close this Lost report? It will no longer appear as an open report.")) return;
    try {
      await publicApi("/api/public/cases/" + encodeURIComponent(state.reference) + "/close", {
        method:"POST", headers:{...credentials,"Content-Type":"application/json"},
        body:JSON.stringify({reason:"no_longer_searching",note:null})
      });
      showToast("Your Lost report has been closed.",false);
      $("#publicTrackForm").requestSubmit();
    } catch(error) { showToast(error.message,true); }
  } else if (event.target.closest("[data-public-add-evidence]")) {
    $("#publicEvidenceError").textContent = "";
    $("#publicEvidenceText").value = "";
    $("#publicEvidenceDialog").showModal();
  }
});
$("#publicEvidenceClose").addEventListener("click", () => $("#publicEvidenceDialog").close());
$("#publicEvidenceCancel").addEventListener("click", () => $("#publicEvidenceDialog").close());
$("#publicEvidenceForm").addEventListener("submit", async event => {
  event.preventDefault();
  if (!lastPublicTracking) return;
  const evidence = $("#publicEvidenceText").value.trim();
  if (evidence.length < 20) { $("#publicEvidenceError").textContent = "Please enter at least 20 characters."; return; }
  const button = $("#publicEvidenceSubmit");
  button.disabled = true;
  try {
    const state = lastPublicTracking;
    const result = await publicApi("/api/public/claims/" + encodeURIComponent(state.reference) + "/evidence", {
      method:"POST",
      headers:{...getPublicAccess(state.reference, state.roll),"Content-Type":"application/json"},
      body:JSON.stringify({evidence})
    });
    $("#publicEvidenceDialog").close();
    showToast(result.message || "Additional evidence submitted.",false);
    $("#publicTrackForm").requestSubmit();
  } catch(error) { $("#publicEvidenceError").textContent = error.message; }
  finally { button.disabled = false; }
});

function assertLocalOfficeLoginAllowed() {
  if (!appConfig) {
    throw new Error("LostLink configuration has not loaded. Refresh the page before signing in.");
  }
  if (appConfig.auth_mode === "supabase") {
    throw new Error("Supabase office sign-in is configured, but the authentication client is unavailable. Check the Supabase URL and anon key. Local demo login is disabled.");
  }
}

async function start() {
  showPublicHome();
  // A blank API_BASE_URL means this page is served by the FastAPI backend itself.
  // In that same-origin deployment, relative /api/* requests are valid even when
  // the optional static-host deployment flag says no external backend is configured.
  if (window.LOSTLINK_DEPLOYMENT_CONFIGURED === false && API_BASE_URL) {
    $("#publicApiStatus").textContent = "This preview is not connected to the LostLink API yet. Configure BACKEND_ORIGIN in Vercel after deploying the backend.";
    $("#publicApiStatus").classList.remove("hidden");
    return;
  }
  try {
    await loadConfig();
    $("#publicApiStatus").classList.add("hidden");
  } catch (error) {
    $("#publicApiStatus").textContent = error.message + " Public reporting will be available when the backend is reachable.";
    $("#publicApiStatus").classList.remove("hidden");
    return;
  }
  if (appConfig && appConfig.auth_mode === "supabase") {
    if (!supabaseClient) {
      showPublicHome();
      return;
    }
    try {
      const { data } = await supabaseClient.auth.getSession();
      supabaseAccessToken = data && data.session ? data.session.access_token : null;
      if (!supabaseAccessToken) { showPublicHome(); return; }
      const profile = await api("/api/me");
      if (!profile.user || profile.user.role !== "office") throw new Error("This account is not authorised for LostLink. Office staff access only.");
      enterApp(profile.user);
    } catch (error) {
      supabaseAccessToken = null;
      await supabaseClient?.auth.signOut().catch(() => {});
      showPublicHome();
      $("#publicApiStatus").textContent = error.message;
      $("#publicApiStatus").classList.remove("hidden");
    }
    return;
  }
  try {
    const profile = await api("/api/me");
    if (profile.user && profile.user.role === "office") enterApp(profile.user);
    else showPublicHome();
  } catch (_) {
    showPublicHome();
  }
}

$("#loginForm").addEventListener("submit",async event => {
  event.preventDefault();
  $("#loginError").textContent = "";
  try {
    if (supabaseClient) {
      const email = $("#loginEmail").value.trim().toLowerCase();
      const password = $("#loginPassword").value;
      const {data,error} = await supabaseClient.auth.signInWithPassword({email,password});
      if (error) throw error;
      supabaseAccessToken = data.session.access_token;
      const profile = await api("/api/me");
      if (!profile.user || profile.user.role !== "office") {
        await supabaseClient.auth.signOut();
        supabaseAccessToken = null;
        throw new Error("This account is not on the authorised office staff list.");
      }
      enterApp(profile.user);
    } else {
      assertLocalOfficeLoginAllowed();
      const result = await api("/api/login",{method:"POST",body:{email:$("#loginEmail").value.trim(),password:$("#loginPassword").value}});
      if (!result.user || result.user.role !== "office") throw new Error("Only authorised office staff can sign in.");
      enterApp(result.user);
    }
    showToast("Office staff signed in successfully.",false);
  } catch(error) { $("#loginError").textContent = error.message; }
});

async function launchDemoAccount(email,password) {
  $("#loginError").textContent = "";
  try {
    assertLocalOfficeLoginAllowed();
    const result = await api("/api/login",{method:"POST",body:{email,password}});
    if (!result.user || result.user.role !== "office") throw new Error("Only the office demo account is available.");
    inspectedUser = null;
    $("#returnToDashboardButton").classList.add("hidden");
    enterApp(result.user);
    showToast("Opened the office demo view.",false);
  } catch(error) { $("#loginError").textContent = error.message; }
}
$("#fillOffice").addEventListener("click",() => launchDemoAccount("office@lostlink.local","office123"));
$("#showLoginButton").addEventListener("click",() => {
  inspectedUser = currentUser;
  openPublicOfficeSignIn();
  $("#returnToDashboardButton").classList.toggle("hidden",!inspectedUser);
});
$("#returnToDashboardButton").addEventListener("click",() => {
  if (inspectedUser) { const prior = inspectedUser; inspectedUser = null; enterApp(prior); }
});
$("#logoutButton").addEventListener("click",async() => {
  const button = $("#logoutButton");
  button.disabled = true;
  try {
    if (supabaseClient) {
      const {error} = await supabaseClient.auth.signOut();
      if (error) throw error;
      clearAuthenticatedImages();
      supabaseAccessToken = null;
    } else {
      await api("/api/logout",{method:"POST"});
    }
    if (typeof stopNotificationPolling === "function") stopNotificationPolling();
    inspectedUser = null;
    currentUser = null;
    $("#returnToDashboardButton").classList.add("hidden");
    showPublicHome();
    showToast("You have been signed out.",false);
  } catch (error) {
    showToast(error.message || "Sign out failed. Please try again.",true);
  } finally {
    button.disabled = false;
  }
});
$("#studentNav").addEventListener("click", (event) => {
  const button = event.target.closest("[data-view]");
  if (button) navigate(button.dataset.view);
});
document.addEventListener("click", (event) => {
  const go = event.target.closest("[data-go]");
  if (go) navigate(go.dataset.go);
  const useCategory = event.target.closest("[data-use-category]");
  if (useCategory) {
    const form = useCategory.closest("form");
    if (form) {
      reportField("reportCategory", form).value = useCategory.dataset.useCategory;
      reportField("categorySuggestion", form).textContent = "Category selected. Review it before submitting.";
    }
  }
  const reportKind = event.target.closest("[data-report-kind]");
  if (reportKind) { navigate("report"); setReportMode(reportKind.dataset.reportKind); }
  const detailButton = event.target.closest("[data-view-details]");
  if (detailButton) openItemDetails(detailButton.dataset.viewDetails);
  const notificationMatches = event.target.closest("[data-notification-matches]");
  if (notificationMatches) {
    navigate("my-reports");
    loadMatches(notificationMatches.dataset.notificationMatches);
  }
  const matches = event.target.closest("[data-matches]");
  if (matches) loadMatches(matches.dataset.matches);
  const evidence = event.target.closest("[data-add-evidence]");
  if (evidence) openAdditionalEvidence(evidence.dataset.addEvidence);
  const dispute = event.target.closest("[data-dispute-claim]");
  if (dispute) submitClaimDispute(dispute.dataset.disputeClaim);
  const closeReport = event.target.closest("[data-close-report]");
  if (closeReport) openCloseReport(closeReport.dataset.closeReport, closeReport.dataset.closeType);
  const decision = event.target.closest("[data-decision]");
  if (decision) openDecisionConfirmation(decision.dataset.claimId, decision.dataset.decision);
  const handover = event.target.closest("[data-handover]");
  if (handover) {
    const itemTitle = handover.closest(".list-card")?.querySelector("h3")?.textContent || "this item";
    openHandoverDialog(handover.dataset.handover, itemTitle, handover.dataset.roll || "");
  }
  const storageUpdate = event.target.closest("[data-storage-update]");
  if (storageUpdate) {
    const itemTitle = storageUpdate.closest(".list-card")?.querySelector("h3")?.textContent || "Tagged item";
    openStorageUpdate(storageUpdate.dataset.storageUpdate, storageUpdate.dataset.currentLocation, itemTitle);
  }
  const notification = event.target.closest("[data-notification-read]");
  if (notification) markNotificationRead(notification.dataset.notificationRead);
  const privacyReview = event.target.closest("[data-privacy-review]");
  if (privacyReview) openPrivacyDecision(privacyReview.dataset.privacyReview, privacyReview.dataset.privacyType, privacyReview.dataset.privacySubject);
  const certificate = event.target.closest("[data-certificate-download]");
  if (certificate) { if (usingMockApi) mockCertificateDownload(certificate.dataset.certificateDownload); else downloadAuthenticatedFile("/api/certificates/" + encodeURIComponent(certificate.dataset.certificateDownload) + "/download", "lostlink-certificate-" + certificate.dataset.certificateDownload + ".pdf").catch((error) => showToast(error.message, true)); }
});
$("#browseLoadMore").addEventListener("click", () => loadBrowse(true));
$("#myReportsLoadMore").addEventListener("click", () => loadMyReports(true));
$("#myClaimsLoadMore").addEventListener("click", () => loadMyClaims(true));
$("#intakeLoadMore").addEventListener("click", () => loadOffice("intake"));
$("#inventoryLoadMore").addEventListener("click", () => loadOffice("inventory"));
$("#officeClaimsLoadMore").addEventListener("click", () => loadOffice("officeClaims"));
$("#handoverLoadMore").addEventListener("click", () => loadOffice("handovers"));
$("#searchForm").addEventListener("submit", (event) => { event.preventDefault(); loadBrowse(); });
$("#readAllNotifications").addEventListener("click", markAllNotificationsRead);
$("#refreshPrivacyRequests").addEventListener("click", () => loadOffice("privacyRequests"));
$("#privacyDecisionForm").addEventListener("submit", submitPrivacyDecision);
$("#closePrivacyDecision").addEventListener("click", () => { $("#privacyDecisionDialog").close(); selectedPrivacyRequestId = null; });
$("#cancelPrivacyDecision").addEventListener("click", () => { $("#privacyDecisionDialog").close(); selectedPrivacyRequestId = null; });
$("#clearFilters").addEventListener("click", resetSearch);
document.querySelectorAll("#lostReportForm, #foundReportForm").forEach((form) => {
  form.addEventListener("submit", submitReport);
  const categoryButton = form.querySelector(form.id === "foundReportForm" ? "#suggestCategoryButtonFound" : "#suggestCategoryButton");
  const backButton = form.querySelector(form.id === "foundReportForm" ? "#backToReportTypesFound" : "#backToReportTypes");
  const cancelButton = form.querySelector(form.id === "foundReportForm" ? "#cancelReportFound" : "#cancelReport");
  const imageInput = reportField("reportImage", form);
  if (categoryButton) categoryButton.addEventListener("click", suggestReportCategory);
  if (backButton) backButton.addEventListener("click", resetReportMode);
  if (cancelButton) cancelButton.addEventListener("click", () => { resetReportMode(); navigate("browse"); });
  if (imageInput) imageInput.addEventListener("change", () => {
    const label = reportField("imageLabel", form);
    const file = imageInput.files[0];
    if (label) label.textContent = file ? file.name : "Choose a photo";
  });
});
$("#claimEvidenceImage").addEventListener("change", () => {
  const file = $("#claimEvidenceImage").files[0];
  $("#claimEvidenceImageLabel").textContent = file ? file.name : "Attach one supporting photo (optional)";
});
$("#claimForm").addEventListener("submit", submitClaim);
$("#closeItemDetails").addEventListener("click", () => { $("#itemDetailsDialog").close(); selectedDetailsReportId = null; });
$("#cancelItemDetails").addEventListener("click", () => { $("#itemDetailsDialog").close(); selectedDetailsReportId = null; });
$("#itemDetailsClaimButton").addEventListener("click", () => {
  const reportId = selectedDetailsReportId;
  const report = reportId ? findReportById(reportId) : null;
  $("#itemDetailsDialog").close();
  selectedDetailsReportId = null;
  if (report) openPublicClaimDialog(report);
  else if (reportId) openPublicClaimById(reportId);
});
document.addEventListener("contextmenu", (event) => {
  if (event.target.closest(".item-visual img, .item-detail-photo, .evidence-image-preview img")) event.preventDefault();
});
document.addEventListener("dragstart", (event) => {
  if (event.target.matches(".item-visual img, .item-detail-photo, .evidence-image-preview img")) event.preventDefault();
});
$("#decisionConfirmForm").addEventListener("submit", submitDecision);
$("#closeDecisionConfirm").addEventListener("click", () => {
  if (claimDecisionSubmitting) return;
  $("#decisionConfirmDialog").close();
  selectedDecisionClaimId = null;
  selectedDecisionAction = null;
});
$("#cancelDecisionConfirm").addEventListener("click", () => {
  if (claimDecisionSubmitting) return;
  $("#decisionConfirmDialog").close();
  selectedDecisionClaimId = null;
  selectedDecisionAction = null;
});
$("#decisionConfirmDialog").addEventListener("cancel", (event) => {
  if (claimDecisionSubmitting) {
    event.preventDefault();
    return;
  }
  selectedDecisionClaimId = null;
  selectedDecisionAction = null;
});
$("#handoverForm").addEventListener("submit", submitHandover);
$("#closeHandover").addEventListener("click", () => { $("#handoverDialog").close(); selectedHandoverClaimId = null; });
$("#cancelHandover").addEventListener("click", () => { $("#handoverDialog").close(); selectedHandoverClaimId = null; });
$("#additionalEvidenceForm").addEventListener("submit", submitAdditionalEvidence);
$("#closeAdditionalEvidence").addEventListener("click", () => { $("#additionalEvidenceDialog").close(); selectedEvidenceClaimId = null; });
$("#cancelAdditionalEvidence").addEventListener("click", () => { $("#additionalEvidenceDialog").close(); selectedEvidenceClaimId = null; });
$("#storageUpdateForm").addEventListener("submit", submitStorageLocation);
$("#closeStorageUpdate").addEventListener("click", () => { $("#storageUpdateDialog").close(); selectedStorageReportId = null; });
$("#cancelStorageUpdate").addEventListener("click", () => { $("#storageUpdateDialog").close(); selectedStorageReportId = null; });
$("#closeReportForm").addEventListener("submit", submitCloseReport);
$("#closeCloseReport").addEventListener("click", () => { $("#closeReportDialog").close(); selectedCloseReportId = null; selectedCloseReportType = null; });
$("#cancelCloseReport").addEventListener("click", () => { $("#closeReportDialog").close(); selectedCloseReportId = null; selectedCloseReportType = null; });
$("#closeClaim").addEventListener("click", () => $("#claimDialog").close());
$("#cancelClaim").addEventListener("click", () => $("#claimDialog").close());
$("#closeMatches").addEventListener("click", () => $("#matchesPanel").classList.add("hidden"));
$("#finnCharacter").addEventListener("click", () => { const tips = ["A useful match starts with a clear item name and category.","Keep one distinctive ownership detail private for the claim review.","Found an item? It becomes searchable after the campus office records it.","Use your case reference in the browser where you submitted it to check updates."]; const node = $("#mascotMessage"); const current = tips.indexOf(node.textContent); setFinnMessage(tips[(current + 1) % tips.length]); });
$("#finnTipsToggle").addEventListener("click", event => { const dock = $("#finnDock"); const hidden = dock.classList.toggle("tips-disabled"); event.currentTarget.setAttribute("aria-pressed",String(hidden)); event.currentTarget.textContent = hidden ? "Show Finn’s tips" : "Hide Finn’s tips"; if (!hidden) setFinnMessage("I’m back! Tap me whenever you need a clue."); });
$("#appView").addEventListener("submit", submitIntake);
$("#browseResults").addEventListener("click", (event) => {
  const button = event.target.closest("[data-claim]");
  if (!button) return;
  event.preventDefault();
  void openPublicClaimById(button.dataset.claim, button.dataset.publicRef || button.closest(".item-card")?.querySelector(".item-ref")?.textContent);
});
$("#matchResults").addEventListener("click", (event) => {
  const button = event.target.closest("[data-claim]");
  if (!button) return;
  event.preventDefault();
  void openPublicClaimById(button.dataset.claim, button.dataset.publicRef || button.closest(".item-card")?.querySelector(".item-ref")?.textContent);
});

async function loadReportForClaimByRef(reportId, publicRef) {
  return openPublicClaimById(reportId, publicRef);
}

observeAuthImages();
start().then(() => {
  const params = new URLSearchParams(window.location.search);
  if (params.has("track")) {
    showPublicDestination("track");
    $("#publicTrackLink").value = window.location.href;
    $("#publicTrackForm").requestSubmit();
  }
});
