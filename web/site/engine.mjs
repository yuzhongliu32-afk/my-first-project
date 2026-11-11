/** Harbourline free presentation engine.
 * Runs in the visitor's browser. No network calls, model calls or Jira writes.
 * Source excerpts were physically verified at export; runtime checks their
 * integrity and exact citation coordinates, not original PDF bytes.
 */
const clone = value => structuredClone(value);
const clock = () => performance.now();
const stamp = () => new Date().toISOString();
const uid = prefix => `${prefix}-${crypto.randomUUID()}`;
const requireValue = (condition, message) => { if (!condition) throw new Error(message); };
export const normalizeQuote = text => String(text ?? '').normalize('NFC').replace(/\s+/gu, ' ').trim();
const keyOf = ref => JSON.stringify([ref.document_id, ref.document_version, ref.page ?? null, ref.line_start, ref.line_end]);
const sourceLike = value => value && typeof value === 'object' && 'document_id' in value && 'source_type' in value;
function* objects(value) {
  if (Array.isArray(value)) { for (const item of value) yield* objects(item); }
  else if (value && typeof value === 'object') { yield value; for (const item of Object.values(value)) yield* objects(item); }
}
async function sha256(value) {
  const bytes = new TextEncoder().encode(JSON.stringify(value));
  const result = await crypto.subtle.digest('SHA-256', bytes);
  return [...new Uint8Array(result)].map(x => x.toString(16).padStart(2, '0')).join('');
}
function seed(data) {
  // The page sets planning_seed to the published, citation-checked agent run (28 WBS); else the original template.
  const full = data?.planning_seed ?? data?.runs?.['integrated-acceptance']?.full;
  requireValue(full?.planning && full?.risk, 'Verified planning template is unavailable.');
  // A published agent run cites the full source library (its own snapshot); its citations were checked on load.
  requireValue(data?.planning_seed || full.source_snapshot_id === data.bootstrap?.project?.snapshot, 'Planning/source snapshot mismatch.');
  return full;
}
export function resolveEvidence(ref, data) {
  requireValue(typeof ref.document_id === 'string' && typeof ref.document_version === 'string', 'Citation identity is missing.');
  requireValue(Number.isInteger(ref.line_start) && Number.isInteger(ref.line_end) && ref.line_start >= 1 && ref.line_start <= ref.line_end, 'Invalid citation line range.');
  requireValue(ref.page == null || Number.isInteger(ref.page) && ref.page >= 1, 'Invalid physical page.');
  let record = data?.evidence?.[keyOf(ref)] ?? data?.extra_evidence?.[keyOf(ref)];  // extra: quotes of server runs, kept outside the hashed set
  if (!record) {
    const original = (data.corpus || []).find(item => keyOf(item) === keyOf(ref));
    if (original) record = {
      document_id: original.document_id, version: original.document_version, page: original.page ?? null,
      start: original.line_start, end: original.line_end,
      lines: [{number: original.line_start, text: original.quote}],
    };
  }
  requireValue(record, 'Citation version, page or exact range is not loaded.');
  requireValue(record.document_id === ref.document_id && record.version === ref.document_version && (record.page ?? null) === (ref.page ?? null) && record.start === ref.line_start && record.end === ref.line_end, 'Citation mapping does not match its identity.');
  const text = record.lines.filter(row => row.number >= ref.line_start && row.number <= ref.line_end).map(row => row.text).join('\n');
  const quote = normalizeQuote(ref.quote);
  requireValue(quote && normalizeQuote(text).includes(quote), 'Evidence quote does not match the cited lines.');
  return clone(record);
}
export function checkEvidence(value, data) {
  let count = 0;
  for (const ref of objects(value)) if (sourceLike(ref)) { resolveEvidence(ref, data); count++; }
  return count;
}
export async function verifyCorpus(data) {
  requireValue(data?.integrity && data?.evidence && Array.isArray(data?.corpus) && data.corpus.length, 'Source integrity manifest is unavailable.');
  requireValue(/^[a-f0-9]{64}$/i.test(data.integrity.evidence_sha256 || '') && /^[a-f0-9]{64}$/i.test(data.integrity.corpus_sha256 || ''), 'Source integrity hashes are invalid.');
  const [evidenceHash, corpusHash] = await Promise.all([sha256(data.evidence), sha256(data.corpus)]);
  requireValue(evidenceHash === data.integrity.evidence_sha256 && corpusHash === data.integrity.corpus_sha256, 'Exported source data changed; execution stopped.');
  const full = seed({...data, planning_seed: undefined});  // the integrity manifest covers the original template
  requireValue(!data.integrity.snapshot || data.integrity.snapshot === full.source_snapshot_id, 'Integrity manifest snapshot mismatch.');
  let count = 0;
  for (const [key, record] of Object.entries(data.evidence)) {
    requireValue(Array.isArray(record.lines) && record.lines.length, 'An evidence excerpt has no source lines.');
    const identity = JSON.parse(key);
    requireValue(JSON.stringify([record.document_id, record.version, record.page ?? null, record.start, record.end]) === JSON.stringify(identity), 'Evidence map identity mismatch.');
    requireValue(record.lines.every((row, i) => Number.isInteger(row.number) && row.number >= record.start && row.number <= record.end && (!i || row.number > record.lines[i - 1].number) && typeof row.text === 'string'), 'Evidence line coordinates are invalid.');
    count++;
  }
  for (const ref of data.corpus) resolveEvidence(ref, data);
  checkEvidence({planning: full.planning, risk: full.risk}, data);
  return {snapshot: full.source_snapshot_id, excerpts_checked: count, corpus_records: data.corpus.length, verified: true,
    method: 'SHA-256 of exported excerpts and exact version/page/line quote checks; original PDFs were verified during export.'};
}
function iso(value, name) {
  requireValue(typeof value === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(value), `${name} must use YYYY-MM-DD.`);
  const time = Date.parse(value + 'T00:00:00Z');
  requireValue(Number.isFinite(time) && new Date(time).toISOString().slice(0, 10) === value, `${name} is not a valid calendar date.`);
  return value;
}
function inputValues(input) {
  requireValue(input && typeof input === 'object', 'Run settings are required.');
  requireValue(['WEEKLY_COMMITTEE', 'MONTHLY_GRANT'].includes(input.report_type), 'Choose a weekly or monthly report.');
  const start = iso(input.start_date, 'Period start'), end = iso(input.end_date, 'Period end'), cutoff = iso(input.as_of_date, 'Evidence cutoff');
  requireValue(start <= end && end <= cutoff, 'Period start must not follow its end; the period must end by the evidence cutoff.');
  requireValue(cutoff >= '2027-04-06', 'This full planning view requires an evidence cutoff of 2027-04-06 or later.');
  const rounds = input.max_review_rounds ?? 2;
  requireValue(Number.isInteger(rounds) && rounds >= 1 && rounds <= 5, 'Review rounds must be an integer from 1 to 5.');
  const weeks = input.delay_weeks ?? 6, cost = input.extra_cost_sgd ?? 600000;
  requireValue(typeof weeks === 'number' && Number.isFinite(weeks) && weeks >= 0 && weeks <= 52, 'Delay assumption must be a finite number from 0 to 52 weeks.');
  requireValue(typeof cost === 'number' && Number.isFinite(cost) && cost >= 0 && cost <= 10000000, 'Cost assumption must be a finite amount from S$0 to S$10,000,000.');
  return {report_type: input.report_type, start, end, cutoff, rounds, weeks, cost};
}
const metrics = started => ({api_calls: 0, input_tokens: 0, output_tokens: 0, estimated_cost_usd: 0, elapsed_seconds: (clock() - started) / 1000});
const emptyMemory = () => ({query:null,answer:null,answer_status:'NOT_RUN',fact_records:[],conflicts:[],decisions:[],citations:[],open_questions:[]});
const uniqueRefs = refs => [...new Map(refs.map(ref => [keyOf(ref) + '\u0000' + ref.quote, clone(ref)])).values()];
function allRefs(value) { return [...objects(value)].filter(sourceLike); }
function checkPlanningContract(planning,risk) {
  const unique=(rows,field)=>{
    requireValue(Array.isArray(rows),`Missing ${field} records.`);
    const ids=rows.map(row=>row[field]);
    requireValue(ids.every(id=>typeof id==='string'&&id.trim())&&new Set(ids).size===ids.length,`Duplicate or empty ${field}.`);
    return new Set(ids);
  };
  const scopes=unique(planning.scope_items,'scope_id'),work=unique(planning.wbs_items,'wbs_id'),milestones=unique(planning.milestones,'milestone_id');
  unique(planning.sponsor_questions,'question_id');const risks=unique(risk.risks,'risk_id');unique(risk.scenarios,'scenario_id');
  const byWork=new Map(planning.wbs_items.map(row=>[row.wbs_id,row]));
  const subset=(values,allowed,message)=>requireValue(Array.isArray(values)&&values.every(value=>allowed.has(value)),message);
  const acyclic=(rows,field,dependencies)=>{
    const graph=new Map(rows.map(row=>[row[field],row[dependencies]])),visiting=new Set(),done=new Set();
    const visit=id=>{
      requireValue(!visiting.has(id),`Dependency cycle in ${field}.`);if(done.has(id))return;
      visiting.add(id);requireValue(Array.isArray(graph.get(id)),`Missing ${dependencies}.`);
      for(const dep of graph.get(id)){requireValue(graph.has(dep),`Unknown ${field} dependency.`);visit(dep);}
      visiting.delete(id);done.add(id);
    };for(const id of graph.keys())visit(id);
  };
  for(const row of planning.wbs_items){
    requireValue(Number.isInteger(row.level)&&row.level>=1&&row.level<=3,'Invalid WBS level.');
    requireValue(row.level===1?row.parent_wbs_id===null:byWork.get(row.parent_wbs_id)?.level===row.level-1,'WBS parent must exist at the preceding level.');
    subset(row.scope_ids,scopes,'Unknown WBS scope.');
  }
  acyclic(planning.wbs_items,'wbs_id','predecessor_wbs_ids');acyclic(planning.milestones,'milestone_id','predecessor_milestone_ids');
  for(const row of planning.milestones)subset(row.related_wbs_ids,work,'Unknown milestone work item.');
  for(const row of planning.sponsor_questions)if(row.status==='ANSWERED')requireValue(row.answer&&row.answer_sources.length,'Answered question needs supporting sources.');
  for(const row of risk.risks){
    subset(row.related_wbs_ids,work,'Unknown risk work item.');subset(row.related_milestone_ids,milestones,'Unknown risk milestone.');
    if(row.probability==null||row.impact==null)requireValue(row.score==null,'A partial risk rating must have null score.');
    else requireValue(Number.isFinite(row.probability)&&Number.isFinite(row.impact)&&row.probability>=1&&row.impact>=1&&row.score===row.probability*row.impact,'Risk score must equal probability × impact.');
  }
  for(const row of risk.scenarios){
    subset(row.affected_wbs_ids,work,'Unknown scenario work item.');subset(row.affected_risk_ids,risks,'Unknown scenario risk.');
    if(row.estimate_status==='QUANTIFIED_ASSUMPTION')requireValue(row.assumptions.length&&row.calculation_basis,'Quantified scenario requires assumptions and calculation basis.');
  }
}
function rebuildPlanning(template, settings) {
  const planning = clone(template.planning), risk = clone(template.risk);
  checkPlanningContract(planning,risk);
  const scenario = risk.scenarios.find(item => item.scenario_id === 'SC01')
    ?? risk.scenarios.find(item => /asbestos/i.test(item.description || '')) ?? risk.scenarios[0];
  requireValue(scenario, 'Source-grounded asbestos scenario is missing.');
  scenario.description = 'Live conditional asbestos-removal sensitivity — user assumptions';
  scenario.schedule_impact_days = settings.weeks * 7;
  scenario.cost_impact_sgd = settings.cost;
  scenario.assumptions = [
    `Presentation input assumes ${settings.weeks} weeks of delay and S$${settings.cost.toLocaleString('en-US')} incremental cost; these are user assumptions, not approved facts.`,
    'One-for-one critical-path propagation and zero recoverable float are assumed; the actual project completion impact is unproven.',
    'The source removal estimate is S$350,000–600,000 and 4–6 weeks. Input outside this range is an illustrative sensitivity, not a revised source estimate.',
    'No variation, baseline, current risk rating or named owner is approved by this run.',
  ];
  scenario.calculation_basis = `${settings.weeks} weeks × 7 = ${scenario.schedule_impact_days} calendar days; incremental cost assumption = S$${settings.cost}. Conditional sensitivity only; source estimates remain unchanged.`;
  scenario.estimate_status = 'QUANTIFIED_ASSUMPTION';
  checkPlanningContract(planning,risk);
  return {planning, risk};
}
function referenceDate(ref, data) {
  const item = (data.corpus || []).find(row => keyOf(row) === keyOf(ref));
  return item?.event_date || item?.issued_at || null;
}
function makeReport(data, planning, risk, settings, id) {
  const references = uniqueRefs(allRefs({planning, risk}));
  const ordered = references.sort((a, b) => {
    const priority = ref => /MAR-PROGRESS|Mar2027/i.test(ref.document_id) ? 0 : /GRANT|Grant/i.test(ref.document_id) ? 1 : /EDC|minutes/i.test(ref.document_id) ? 2 : 3;
    return priority(a) - priority(b);
  });
  // Audience-specific excerpt selection is recomputed, never copied from a saved report.
  const selected = ordered.filter(ref => settings.report_type === 'MONTHLY_GRANT'
    ? /grant|tranche|progress|completion|cost|operator|risk|asbestos|budget/i.test(ref.quote)
    : /progress|closure|asbestos|decision|design|handover|delay|programme|approval/i.test(ref.quote)).slice(0, settings.report_type === 'MONTHLY_GRANT' ? 14 : 10);
  requireValue(selected.length > 0, 'No verified excerpts are available for this report.');
  const sections = selected.map((ref, index) => ({section_id: `SEC-${String(index + 1).padStart(2,'0')}`,
    heading: `${settings.report_type === 'MONTHLY_GRANT' ? 'Grant evidence' : 'Committee evidence'} ${index + 1} — ${ref.document_id}`,
    text: ref.quote, supporting_fact_ids: [], citations: [clone(ref)]}));
  const report = {report_id:`LIVE-${settings.report_type}-${id}`,report_type:settings.report_type,
    audience:settings.report_type === 'MONTHLY_GRANT'?'Grant Body':'Estate Development Committee',
    reporting_period:{start_date:settings.start,end_date:settings.end},source_snapshot_id:templateSnapshot(data),revision:1,
    sections,included_fact_ids:[],open_issues:[
      'This is a newly assembled source-excerpt report, not generated narrative. It does not infer progress inside the chosen period from an undated or cumulative statement.',
      'Source issue dates and event dates may differ. Earlier material is context; later-issued evidence must not be presented as what was known during the reporting week.',
      'Verified spending, grant disbursement and reconciled baseline decisions remain unavailable in this demonstration view.',
      `Live what-if: ${settings.weeks} weeks × 7 = ${settings.weeks * 7} conditional calendar days; S$${settings.cost} input cost assumption. No sponsor approval is inferred.`,
    ],assumptions:[
      `Selected reporting period: ${settings.start} to ${settings.end}; exported-evidence cutoff: ${settings.cutoff}.`,
      'The pre-verified B rule/template reconstructs planning and risk; no fresh planning LLM or original PDF access occurs in the browser.',
      'Rule Critic checks literal evidence integrity only. A human must assess completeness, meaning and release.',
    ],is_stale:false,status:'DRAFT'};
  return report;
}
const templateSnapshot = data => seed(data).source_snapshot_id;
function critique(report, data, reviewRound = 1, maximum = 2) {
  const findings = [];
  const issue = (category, description, section = null) => findings.push({finding_id:`RULE-${findings.length+1}`,category,severity:'BLOCKER',section_id:section,
    description,required_fix:'Restore verified source quotations or obtain additional evidence before review.',citations:[]});
  if (!report.reporting_period.start_date || !report.reporting_period.end_date) issue('MISSING_INFORMATION','A reporting period is required.');
  if (report.is_stale) issue('STALE_DATA','The report is stale; refresh it from reviewed source changes.');
  if (!report.sections.length) issue('MISSING_INFORMATION','No evidence sections were assembled.');
  for (const section of report.sections) {
    try {
      requireValue(section.citations.length, 'No supporting citation.');
      checkEvidence(section, data);
      requireValue(normalizeQuote(section.text) === normalizeQuote(section.citations.map(ref => ref.quote).join('\n\n')), 'Section contains text beyond its exact source quotations.');
    } catch (error) { issue('UNSUPPORTED_CLAIM',error.message,section.section_id); }
  }
  const pass = findings.length === 0;
  return {review_id:uid('RULE-REVIEW'),report_id:report.report_id,review_round:reviewRound,
    verdict:pass?'PASS':'ESCALATE',findings,stop_reason:pass?'PASS':reviewRound>=maximum?'MAX_ROUNDS':'MISSING_EVIDENCE',
    ready_for_human_review:pass&&!report.is_stale,
    reviewer_notes:'Deterministic verbatim-source Critic. PASS confirms citation/text integrity only, not semantic completeness, sponsor approval or release.'};
}
export async function runPresentation(data, input, onEvent = () => {}) {
  const started = clock(), settings = inputValues(input), id = uid('pre'), trace = [];
  const emit = (stage, label, status) => {
    const event = {trace_id:uid('trace'),stage,label,status,at:stamp()};
    trace.push(event); onEvent(clone(event));
  };
  emit('sources','Checking exported source integrity and citation coordinates','RUNNING');
  const sourceCheck = await verifyCorpus(data);
  emit('sources',`Verified ${sourceCheck.excerpts_checked} exported excerpts against their integrity manifest`,'COMPLETE');
  emit('planning','Reconstructing the source-grounded B planning and risk template','RUNNING');
  const base = seed(data), {planning,risk} = rebuildPlanning(base,settings);
  checkEvidence({planning,risk},data);
  emit('planning',`Rebuilt ${planning.wbs_items.length} work items and recomputed the live what-if`,'COMPLETE');
  emit('handoff','A checked B evidence and passed the validated planning/risk context to the report builder','COMPLETE');
  const report = makeReport(data,planning,risk,settings,id);
  checkEvidence(report,data);
  emit('reporting',`Assembled a new ${settings.report_type==='MONTHLY_GRANT'?'monthly grant':'weekly committee'} source-excerpt report`,'COMPLETE');
  const reviews = [];
  for (let round=1; round<=settings.rounds; round++) {
    const review = critique(report,data,round,settings.rounds);reviews.push(review);
    if (review.verdict === 'PASS') {report.status='READY_FOR_HUMAN_REVIEW';break;}
    if (review.verdict === 'ESCALATE' || round===settings.rounds) {report.status='BLOCKED';break;}
  }
  emit('critic',reviews.at(-1).verdict==='PASS'?'Rule Critic passed exact quote checks; human review remains required':'Rule Critic stopped the report',reviews.at(-1).verdict==='PASS'?'COMPLETE':'FAILED');
  const sourceRefs = uniqueRefs(allRefs({planning,risk,report}));
  const full = {
    schema_version:base.schema_version,message_id:uid('A'),run_id:id,project_id:base.project_id,producer:'A',recipient:'HUMAN',operation:'FULL_RUN',
    status:report.status==='BLOCKED'?'BLOCKED':'PARTIAL',source_snapshot_id:base.source_snapshot_id,
    request:{question:null,requested_report_type:settings.report_type,reporting_period:{start_date:settings.start,end_date:settings.end},
      target_ids:[],instructions:'Live free browser execution over exported verified course excerpts and a source-grounded planning template. No model call, Jira write or human approval.',max_review_rounds:settings.rounds},
    source_evidence:sourceRefs,integration:{jira_project_key:null,jira_actions:[],handoff_completed:true,handoff_trace_ids:trace.map(x=>x.trace_id)},
    change:{events:[],stale_artifacts:[],human_actions:[]},
    governance:{approvals:[],audit_entries:[],fairness_checks:clone(base.governance.fairness_checks),incidents:[]},
    metrics:metrics(started),errors:[{code:'HUMAN_REVIEW_REQUIRED',message:'Current baseline, risk ownership, source gaps, consultation fairness and report release remain human decisions. Literal quote checks do not resolve them.',recoverable:true}],
    planning,risk,memory:emptyMemory(),reporting:{reports:[report],critic_reviews:reviews},
  };
  emit('human','Run completed without publishing, approving or writing to Jira','COMPLETE');
  full.integration.handoff_trace_ids=trace.map(x=>x.trace_id);full.metrics=metrics(started);
  checkEvidence(full,data);
  return {id,mode:'live',provider:'extractive',operation:'presentation_run',full,trace,created_at:stamp(),as_of_date:settings.cutoff,
    notice:'Live free browser execution: template-based planning, input-based what-if calculation, new quote-only report and deterministic Critic. No fresh PDF access, paid model call, Jira write or human approval.',
    integrity_check:sourceCheck};
}
const STOP_WORDS = new Set('a an the is are was were what who where when how does do did has have had to in of for with on and or by from at can could would should this that about tell me much many please harbourline community hub refurbishment project'.split(' '));
const stem = term => ({closures:'closure',lifts:'lift',risks:'risk',operators:'operator',conditions:'condition',tranches:'tranche',costs:'cost',weeks:'week',dates:'date',milestones:'milestone'}[term] || term);
function termsFor(question) {
  const aliases = [];
  const mappings = [[/预算|預算|资金|資金/u,'approved budget'],[/封闭|封閉|关闭|關閉|闭馆|閉館/u,'closures council'],[/石棉/u,'asbestos chrysotile'],[/拨款|撥款|资助|資助/u,'grant tranche'],[/幼儿|幼兒|托儿|托兒/u,'childcare handover'],[/风险|風險/u,'risk'],[/电梯|電梯/u,'lift closures'],[/屋顶|屋頂/u,'rooftop garden']];
  for (const [pattern,text] of mappings) if(pattern.test(question)) aliases.push(text);
  requireValue(/[A-Za-z]/.test(question) || aliases.length, 'Use English source keywords, or the budget, closure and asbestos example topics.');
  const text=question+' '+aliases.join(' ');
  return [...new Set((text.toLowerCase().match(/[a-z0-9]+/g)||[]).filter(t=>t.length>1&&!STOP_WORDS.has(t)).map(stem))];
}
function cleanRef(row) {
  return {document_id:row.document_id,document_version:row.document_version,source_type:row.source_type,page:row.page??null,
    line_start:row.line_start,line_end:row.line_end,chunk_id:row.chunk_id??null,quote:row.quote};
}
export async function retrieve(data, input) {
  const started=clock();
  requireValue(typeof input?.question==='string' && input.question.trim().length>0 && input.question.length<=2000,'Enter a question of 1–2000 characters.');
  const cutoff=iso(input.as_of_date,'Evidence cutoff');
  await verifyCorpus(data);
  const terms=termsFor(input.question);
  requireValue(terms.length>0,'Enter at least one specific source keyword.');
  const ranked=[];
  const historicalRequested=/seabreeze|historical|lessons?\s+learned/i.test(input.question);
  for (const row of data.corpus) {
    const historical=/Seabreeze|PACK-LESSONS|Lessons_learned/i.test(row.document_id);
    if(historical&&!historicalRequested)continue;
    const issued=row.event_date || row.issued_at;
    if (!issued || !/^\d{4}-\d{2}-\d{2}$/.test(issued) || issued>cutoff) continue;
    const words=new Set((row.quote.toLowerCase().match(/[a-z0-9]+/g)||[]).map(stem));
    const hits=terms.filter(term=>words.has(term));
    const minimum=terms.length<=2?1:Math.ceil(terms.length*0.6);
    const focus=terms.filter(term=>!['approved','council','name','number','final','record','source'].includes(term));
    if (focus.length && !focus.some(term=>words.has(term))) continue;
    if (hits.length>=minimum) ranked.push({row,score:hits.length+hits.filter(term=>term!=='approved'&&term!=='council').length*0.2});
  }
  ranked.sort((a,b)=>b.score-a.score||a.row.document_id.localeCompare(b.row.document_id)||a.row.line_start-b.row.line_start);
  const distinct=[];const seenQuotes=new Set();
  for(const item of ranked){const quote=normalizeQuote(item.row.quote);if(!seenQuotes.has(quote)){distinct.push(cleanRef(item.row));seenQuotes.add(quote);}if(distinct.length===3)break;}
  const refs=distinct;checkEvidence({citations:refs},data);
  const memory={...emptyMemory(),query:input.question.trim(),answer:refs.length?refs.map(r=>r.quote).join('\n\n'):'NOT FOUND in the loaded, date-eligible presentation excerpts.',
    answer_status:refs.length?'PARTIAL':'NOT_FOUND',citations:refs,
    fact_records:refs.map((ref,i)=>({fact_id:`LIVE-FACT-${i+1}`,statement:ref.quote,status:'SUPPORTED',source_refs:[clone(ref)],
      related_scope_ids:[],related_wbs_ids:[],related_milestone_ids:[],related_risk_ids:[]})),
    open_questions:refs.length?['These are retrieved quotations, not a generated semantic answer. A human must decide whether they fully answer the question.']:[]};
  if(refs.some(r=>/Seabreeze|PACK-LESSONS|Lessons_learned/i.test(r.document_id)))memory.open_questions.push('Historical Seabreeze lessons are not evidence that the same event occurred at Harbourline.');
  return {mode:'live_extractive',memory,metrics:metrics(started),notice:'Computed now by free lexical retrieval over loaded verified excerpts. Unknown-dated and future sources are excluded; NOT_FOUND refers to this excerpt set, not every original file.'};
}
export async function runCriticTest(data,view) {
  const started=clock();await verifyCorpus(data);checkEvidence(view.full,data);
  const sourceReport=view.full.reporting.reports[0];
  requireValue(sourceReport?.sections?.length,'The selected record has no report for the Critic test.');
  const report=clone(sourceReport);report.is_stale=false;
  report.sections=report.sections.filter(s=>s.citations.length).map(s=>({...s,text:s.citations.map(ref=>ref.quote).join('\n\n')}));
  requireValue(report.sections.length,'No source-backed section is available.');
  const baseline=critique(report,data,1,2);
  requireValue(baseline.verdict==='PASS','The quote-only test control did not pass; test stopped.');
  report.sections[0].text+='\nTEST UNSUPPORTED CLAIM: The sponsor approved a S$99 million final budget.';
  const review=critique(report,data,1,2);
  requireValue(review.verdict==='ESCALATE'&&review.findings.length===1,'The planted-fault test did not isolate one unsupported claim.');
  return {baseline_review:baseline,review,notice:'TEST: a new quote-only control passed, then one unsourced S$99 million sentence was added and blocked. This is not a new factual budget or an LLM evaluation.',
    operation_metrics:metrics(started),mode:'live_extractive_test',base_run_id:view.id};
}
export async function applyChange(data,view) {
  const started=clock();await verifyCorpus(data);checkEvidence(view.full,data);
  const report=view.full.reporting.reports[0];requireValue(report,'The selected record has no report to mark stale.');
  const ref=allRefs(view.full.risk.scenarios).find(r=>/asbestos|chrysotile/i.test(r.quote));
  requireValue(ref,'The asbestos test source is unavailable.');
  const changed=clone(view.full),id=uid('change'),changeId=uid('TEST-SOURCE-CHANGE');
  const affected=[...new Set(changed.risk.scenarios.flatMap(s=>[...s.affected_wbs_ids,...s.affected_risk_ids]))];
  const proposedSnapshot=(await sha256({previous:changed.source_snapshot_id,change:changeId})).slice(0,12);
  changed.change.events.push({change_id:changeId,description:'TEST: use the existing asbestos excerpt to demonstrate stale-output handling; not a new project fact or the official Week 12 event.',source_refs:[clone(ref)],status:'PROPOSED',approval_id:null,affected_ids:affected});
  for(const [artifact_id,artifact_type] of [['PLAN','PLAN'],['RISK_REGISTER','RISK_REGISTER']])changed.change.stale_artifacts.push({artifact_id,artifact_type,previous_snapshot_id:changed.source_snapshot_id,current_snapshot_id:proposedSnapshot,reason:changeId,suggested_action:'Human must verify the real event and approve a reconciled baseline before refresh.'});
  for(const item of changed.reporting.reports){item.is_stale=true;item.status='BLOCKED';changed.change.stale_artifacts.push({artifact_id:item.report_id,artifact_type:item.report_type==='WEEKLY_COMMITTEE'?'WEEKLY_REPORT':'MONTHLY_REPORT',previous_snapshot_id:changed.source_snapshot_id,current_snapshot_id:proposedSnapshot,reason:changeId,suggested_action:'Regenerate using reviewed evidence, pass Critic, then obtain human release approval.'});}
  for(const item of changed.reporting.critic_reviews)item.ready_for_human_review=false;
  changed.change.human_actions=['Verify the official event and its authority.','Reassess affected work, dependencies, risk ratings and conditional cost/schedule assumptions.','Prepare a new source bundle and rerun the report and Critic.','Obtain new human approval before external writes or release.'];
  changed.status='BLOCKED';
  checkEvidence(changed,data);
  return {run:{...clone(view),id,mode:'live',operation:'change_demo',base_run_id:view.id,full:changed,created_at:stamp(),
    operation_metrics:metrics(started),notice:'TEST stale copy only. Original report, source facts and historical approvals remain unchanged; no approval is granted to this change.'},
    notice:'TEST change computed now. The official Week 12 event has not been supplied.'};
}
