"use strict";
const $ = (selector) => document.querySelector(selector);
const state = {accounts: [], overview: null, activity: [], page: 1, pageSize: 8, total: 0, totalPages: 0, account: "", type: "", search: "", view: "overview", form: null, busy: false, activityRequest: 0};
const escapeHTML = (value) => String(value).replace(/[&<>"']/g, (char) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[char]));
const icon = (name, className = "") => `<svg class="${className}" aria-hidden="true"><use href="#i-${name}"/></svg>`;
function formatMoney(value) {
  const [whole, fraction = "00"] = String(value ?? "0.00").split(".");
  return "$" + BigInt(whole).toLocaleString("en-US") + "." + fraction.padEnd(2, "0");
}
const formatDate = (value, options = {month:"short", day:"numeric", year:"numeric"}) => new Date(value).toLocaleDateString("en-US", options);
const ref = () => "TXN-" + crypto.randomUUID().slice(0, 8).toUpperCase();
let toastTimer;
function toast(message) {
  $("#toast-text").textContent = message;
  $("#toast").hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { $("#toast").hidden = true; }, 5000);
}
async function api(path, options = {}) {
  let response;
  try { response = await fetch(path, {headers:{"Content-Type":"application/json"}, ...options}); }
  catch { throw new Error("Couldn't reach the server. Check your connection and try again."); }
  let data;
  try { data = await response.json(); } catch { throw new Error("The server returned an unexpected response. Please try again."); }
  if (!response.ok) {
    const error = data.error || {};
    const detail = error.details?.[0];
    throw new Error(detail ? `${detail.field.replace(/^body\./, "").replaceAll("_", " ")}: ${detail.message}` : (error.message || "Something went wrong. Please try again."));
  }
  return data;
}
function showPageError(message = "") { $("#page-error").textContent = message; $("#page-error").hidden = !message; }
async function loadAccounts() {
  const accounts = [];
  for (let page = 1; ; page++) {
    const result = await api(`/accounts?page=${page}&page_size=100`);
    accounts.push(...result.data);
    if (page >= result.pagination.total_pages) break;
  }
  state.accounts = accounts.sort((a,b) => a.id - b.id);
  renderAccounts();
  const accountSelect = $("#filter-account");
  accountSelect.innerHTML = `<option value="">All accounts</option>` + state.accounts.map((account) => `<option value="${account.id}">${escapeHTML(account.name)}</option>`).join("");
  accountSelect.value = state.account;
}
function renderAccounts() {
  const accounts = state.view === "accounts" && state.search ? state.accounts.filter(a => a.name.toLowerCase().includes(state.search.toLowerCase())) : state.accounts;
  $("#account-badge").textContent = state.accounts.length;
  $("#nav-count").textContent = state.accounts.length;
  $("#account-cards").innerHTML = accounts.length ? accounts.map(account => `<button class="account-card" data-account="${account.id}" aria-label="View ${escapeHTML(account.name)} transactions"><span class="account-top"><span class="account-icon">${icon("wallet")}</span><strong>${escapeHTML(account.name)}</strong></span><span class="account-balance">${formatMoney(account.balance)}</span><span class="account-footer"><span class="account-id">ACCOUNT ${String(account.id).padStart(4,"0")} <span aria-hidden="true">·</span> USD</span>${icon("chevron")}</span></button>`).join("") : `<div class="empty-state"><h3>${state.accounts.length ? "No matching accounts" : "Your workspace starts here."}</h3><p>${state.accounts.length ? "Try a different account name." : "Create your first account, or explore with sample data."}</p>${state.accounts.length ? "" : '<button class="button primary" data-action="account">Create account</button><button class="button secondary" data-action="seed">Load sample data</button>'}</div>`;
}
function renderOverview() {
  const summary = state.overview;
  $("#total-balance").textContent = formatMoney(summary.total_balance);
  $("#account-count").textContent = summary.account_count;
  $("#credited").textContent = formatMoney(summary.credited);
  $("#debited").textContent = formatMoney(summary.debited);
  const maximum = Math.max(1, ...summary.daily.flatMap(day => [Number(day.credit), Number(day.debit)]));
  const axisAmount = (value) => value >= 1000000 ? `$${(value/1000000).toFixed(1)}m` : value >= 1000 ? `$${(value/1000).toFixed(1)}k` : `$${value.toFixed(0)}`;
  $("#chart").innerHTML = `<div class="chart-axis"><span>${axisAmount(maximum)}</span><span>${axisAmount(maximum*2/3)}</span><span>${axisAmount(maximum/3)}</span><span>$0</span></div><div class="chart-bars">` + summary.daily.map(day => `<div class="chart-day" aria-label="${escapeHTML(day.date)}: credited ${formatMoney(day.credit)}, debited ${formatMoney(day.debit)}"><div class="bar" style="height:${Number(day.credit)/maximum*100}%" title="Credit: ${formatMoney(day.credit)}"></div><div class="bar debit" style="height:${Number(day.debit)/maximum*100}%" title="Debit: ${formatMoney(day.debit)}"></div><span class="day-label">${formatDate(day.date+"T12:00:00",{weekday:"short"})}</span></div>`).join("") + `</div>`;
}
function activityQuery(page = state.page, pageSize = state.pageSize) {
  const params = new URLSearchParams({page, page_size:pageSize});
  if (state.account) params.set("account_id",state.account);
  if (state.type) params.set("type",state.type);
  if (state.search) params.set("q",state.search);
  return "/activity?" + params;
}
async function loadActivity() {
  const request = ++state.activityRequest;
  const result = await api(activityQuery());
  if (request !== state.activityRequest) return;
  state.activity = result.data;
  state.total = result.pagination.total;
  state.totalPages = result.pagination.total_pages;
  renderActivity();
}
function renderActivity() {
  $("#transaction-count").textContent = state.total;
  $("#activity-rows").innerHTML = state.activity.length ? state.activity.map(transaction => `<tr><td><div class="transaction-cell"><span class="movement-icon ${transaction.type}">${icon(transaction.type === "credit" ? "down" : "up")}</span><div><div class="transaction-name">${transaction.transfer_id ? "Account transfer" : transaction.type === "credit" ? "Credit received" : "Debit payment"}</div><div class="transaction-reference" title="${escapeHTML(transaction.reference_id)}">${escapeHTML(transaction.reference_id)}</div></div></div></td><td><span class="account-pill" title="${escapeHTML(transaction.account_name)}">${escapeHTML(transaction.account_name)}</span></td><td>${formatDate(transaction.created_at)}</td><td class="numeric amount-${transaction.type}">${transaction.type === "credit" ? "+" : "−"}${formatMoney(transaction.amount)}</td><td class="numeric">${formatMoney(transaction.balance_after)}</td><td><button class="table-detail" data-detail="${transaction.id}" aria-label="View transaction ${transaction.id}">${icon("chevron")}</button></td></tr>`).join("") : `<tr><td colspan="6" class="table-empty"><strong>${state.search || state.account || state.type ? "No matching transactions" : "A fresh start."}</strong>${state.search || state.account || state.type ? "Adjust the filters to find what you're looking for." : "Your credits, debits, and transfers will appear here."}</td></tr>`;
  const start = state.total ? (state.page-1)*state.pageSize+1 : 0;
  $("#pagination-label").textContent = `Showing ${start}–${Math.min(state.page*state.pageSize,state.total)} of ${state.total} transactions`;
  $("#page-number").textContent = `Page ${state.page}`;
  $("#previous-page").disabled = state.page <= 1;
  $("#next-page").disabled = state.page >= state.totalPages;
}
async function refresh() {
  $("#refresh-button").classList.add("spinning");
  try {
    const [summary] = await Promise.all([api("/overview"), loadAccounts(), loadActivity()]);
    state.overview = summary;
    renderOverview();
    showPageError();
  } catch(error) { showPageError(error.message); }
  finally { $("#refresh-button").classList.remove("spinning"); }
}
function setView() {
  const requested = location.hash.slice(1);
  state.view = ["overview","accounts","activity"].includes(requested) ? requested : "overview";
  document.body.className = "view-" + state.view;
  document.querySelectorAll("[data-nav]").forEach(item => { item.classList.toggle("active",item.dataset.nav === state.view); if(item.dataset.nav === state.view) item.setAttribute("aria-current","page"); else item.removeAttribute("aria-current"); });
  const titles = {overview:["Your money, in view.","A clear picture of every account and every movement."], accounts:["A place for every purpose.","Organize your funds, one account at a time."],activity:["Every movement matters.","A complete record of your credits, debits, and transfers."]};
  $("#breadcrumb").textContent = state.view[0].toUpperCase()+state.view.slice(1);
  $("#page-title").textContent = titles[state.view][0];
  $("#page-description").textContent = titles[state.view][1];
  $("#main-action").dataset.action = state.view === "accounts" ? "account" : "transaction";
  $("#main-action span").textContent = state.view === "accounts" ? "New account" : "New transaction";
  $("#activity-title").firstChild.textContent = state.view === "activity" ? "All activity " : "Recent activity ";
  renderAccounts();
  document.title = `${$("#breadcrumb").textContent} · Atomic Ledger`;
}
function options(selected = "") {
  return state.accounts.map(a => `<option value="${a.id}" ${String(a.id)===String(selected) ? "selected" : ""}>${escapeHTML(a.name)} · ${formatMoney(a.balance)}</option>`).join("");
}
function openForm(kind) {
  if (state.busy) return;
  if (kind !== "account" && !state.accounts.length) { toast("Create an account to get started."); kind = "account"; }
  if (kind === "transfer" && state.accounts.length < 2) { toast("Create a second account to make a transfer."); kind = "account"; }
  state.form = kind;
  $("#form-error").hidden = true;
  const titles = {account:["Create an account","Give your funds a purpose. Every new account starts at $0.00.","Create account"],transaction:["New transaction","Record a credit or debit against one of your accounts.","Add transaction"],transfer:["Move money","Transfer funds between your accounts, in one atomic operation.","Confirm transfer"]};
  $("#dialog-title").textContent = titles[kind][0];
  $("#dialog-description").textContent = titles[kind][1];
  $("#submit-button").textContent = titles[kind][2];
  $("#submit-button").disabled = false;
  const common = `<label for="amount">Amount <span class="field-help">(USD)</span></label><input id="amount" name="amount" type="number" inputmode="decimal" min="0.01" max="999999999999.99" step="0.01" placeholder="0.00" required><label for="reference">Reference ID</label><input id="reference" name="reference_id" maxlength="128" value="${ref()}" required><p class="field-help">A unique reference helps prevent duplicate transactions.</p>`;
  if (kind === "account") $("#form-fields").innerHTML = `<label for="account-name">Account name</label><input id="account-name" name="name" placeholder="e.g. Travel savings" maxlength="100" required autocomplete="off"><p class="field-help">Choose a name that makes this account easy to recognize.</p>`;
  else if (kind === "transaction") $("#form-fields").innerHTML = `<div class="type-switch"><label class="type-choice"><input type="radio" name="type" value="credit" checked><span class="movement-icon credit">${icon("down")}</span>Credit</label><label class="type-choice"><input type="radio" name="type" value="debit"><span class="movement-icon debit">${icon("up")}</span>Debit</label></div><label for="transaction-account">Account</label><select id="transaction-account" name="account_id" required>${options(state.account)}</select>${common}`;
  else $("#form-fields").innerHTML = `<label for="source-account">From account</label><select id="source-account" name="source_account_id" required>${options(state.account || state.accounts[0].id)}</select><div class="transfer-arrow">${icon("down")}</div><label for="destination-account">To account</label><select id="destination-account" name="destination_account_id" required>${options()}</select>${common}<div class="transfer-summary">${icon("shield")} <strong>One transfer. Both sides in sync.</strong><br>Both balances and ledger entries update together.</div>`;
  if (kind === "transfer") syncDestination();
  $("#form-dialog").showModal();
  if (kind === "account") $("#account-name").focus(); else $("#amount").focus();
}
function syncDestination() {
  const source = $("#source-account"), destination = $("#destination-account");
  for (const item of destination.options) item.disabled = item.value === source.value;
  if (destination.value === source.value) destination.value = [...destination.options].find(item => !item.disabled)?.value || "";
}
async function submitForm(event) {
  event.preventDefault();
  if (state.busy) return;
  const fields = Object.fromEntries(new FormData(event.currentTarget));
  const payload = {...fields};
  for (const key of ["account_id","source_account_id","destination_account_id"]) if(key in payload) payload[key] = Number(payload[key]);
  for (const key of ["name","reference_id"]) if(key in payload) payload[key] = payload[key].trim();
  if (("name" in payload && !payload.name) || ("reference_id" in payload && !payload.reference_id)) { $("#form-error").textContent = "Please enter a value instead of only spaces."; $("#form-error").hidden = false; return; }
  const path = {account:"/accounts",transaction:"/transactions",transfer:"/transfers"}[state.form];
  const message = {account:"Account created. Ready for its first transaction.",transaction:"Transaction recorded. Your balance is up to date.",transfer:"Transfer complete. Both account balances are updated."}[state.form];
  state.busy = true;
  const submit = $("#submit-button"), previousLabel = submit.textContent;
  submit.disabled = true;
  submit.textContent = "Saving…";
  $("#form-error").hidden = true;
  try {
    await api(path,{method:"POST",body:JSON.stringify(payload)});
    $("#form-dialog").close();
    state.page = 1;
    await refresh();
    toast(message);
  } catch(error) { $("#form-error").textContent = error.message; $("#form-error").hidden = false; }
  finally { state.busy = false; submit.disabled = false; submit.textContent = previousLabel; }
}
function showDetail(id) {
  const transaction = state.activity.find(item => item.id === Number(id));
  if (!transaction) return;
  const fields = [["Account", transaction.account_name],["Reference",transaction.reference_id],["Transaction ID",`#${transaction.id}`],["Type",transaction.type === "credit" ? "Credit" : "Debit"],["Date",new Date(transaction.created_at).toLocaleString("en-US",{dateStyle:"medium",timeStyle:"short"})],["Balance after",formatMoney(transaction.balance_after)]];
  if(transaction.transfer_id) fields.push(["Transfer ID",`#${transaction.transfer_id}`]);
  $("#detail-content").innerHTML = `<div class="detail-amount amount-${transaction.type}">${transaction.type==="credit" ? "+" : "−"}${formatMoney(transaction.amount)}</div><div class="detail-status">${icon("check")}Completed</div><dl class="detail-list">${fields.map(([label,value]) => `<dt>${label}</dt><dd>${escapeHTML(value)}</dd>`).join("")}</dl>`;
  $("#detail-dialog").showModal();
}
async function seedDemo(button) {
  button.disabled = true;
  try { const result = await api("/demo/seed",{method:"POST",body:"{}"}); await refresh(); toast(result.seeded ? "Sample workspace is ready. Make it your own." : "Your workspace already has accounts; existing data was preserved."); }
  catch(error) { showPageError(error.message); }
  finally { button.disabled = false; }
}
async function exportCSV() {
  const button = $("#export-button");
  button.disabled = true;
  try {
    const rows = [["ID","Account","Type","Amount USD","Balance after USD","Reference","Transfer ID","Created at UTC"]];
    for(let page = 1; ; page++) {
      const result = await api(activityQuery(page,100));
      for(const item of result.data) rows.push([item.id,item.account_name,item.type,item.amount,item.balance_after,item.reference_id,item.transfer_id ?? "",item.created_at]);
      if(page >= result.pagination.total_pages) break;
    }
    const cell = (value) => '"' + String(value).replace(/^[=+\-@\t\r]/,"'$&").replaceAll('"','""') + '"';
    const url = URL.createObjectURL(new Blob(["\uFEFF" + rows.map(row => row.map(cell).join(",")).join("\r\n")],{type:"text/csv;charset=utf-8"}));
    const anchor = document.createElement("a"); anchor.href = url; anchor.download = "atomic-ledger-activity.csv"; anchor.click(); setTimeout(() => URL.revokeObjectURL(url),1000);
    toast(`Exported ${rows.length-1} transactions.`);
  } catch(error) { showPageError(error.message); }
  finally { button.disabled = false; }
}
document.addEventListener("click",event => {
  const action = event.target.closest("[data-action]");
  if(action) {
    const name = action.dataset.action;
    if(["account","transaction","transfer"].includes(name)) openForm(name);
    else if(name === "close-dialog" && !state.busy) $("#form-dialog").close();
    else if(name === "close-detail") $("#detail-dialog").close();
    else if(name === "seed") seedDemo(action);
  }
  const account = event.target.closest("[data-account]");
  if(account) { state.account = account.dataset.account; $("#filter-account").value = state.account; state.page=1; location.hash="activity"; loadActivity().catch(error => showPageError(error.message)); }
  const detail = event.target.closest("[data-detail]");
  if(detail) showDetail(detail.dataset.detail);
});
$("#ledger-form").addEventListener("submit",submitForm);
$("#form-fields").addEventListener("change",event => { if(event.target.id === "source-account") syncDestination(); });
$("#form-dialog").addEventListener("cancel",event => { if(state.busy) event.preventDefault(); });
$("#refresh-button").addEventListener("click",refresh);
$("#export-button").addEventListener("click",exportCSV);
for(const [selector,key] of [["#filter-account","account"],["#filter-type","type"]]) $(selector).addEventListener("change",event => {state[key]=event.target.value; state.page=1; loadActivity().catch(error => showPageError(error.message));});
let searchTimer;
$("#search").addEventListener("input",event => {state.search=event.target.value.trim();state.page=1;clearTimeout(searchTimer);searchTimer=setTimeout(() => {renderAccounts();loadActivity().catch(error => showPageError(error.message));},250);});
for(const [selector,delta] of [["#previous-page",-1],["#next-page",1]]) $(selector).addEventListener("click",() => {state.page+=delta;loadActivity().catch(error => showPageError(error.message));});
document.addEventListener("keydown",event => { if((event.metaKey||event.ctrlKey) && event.key.toLowerCase()==="k") {event.preventDefault(); if(state.view==="accounts") location.hash="activity";$("#search").focus();} });
window.addEventListener("hashchange",setView);
$("#today").textContent = new Date().toLocaleDateString("en-US",{weekday:"long",month:"long",day:"numeric",year:"numeric"}).toUpperCase();
setView();
refresh();
