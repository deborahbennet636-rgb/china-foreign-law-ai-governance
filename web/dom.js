/* DOM and text helpers. Strings from the dataset only ever become text nodes. */

/* Build an element. Children are nodes or strings; strings become text nodes. */
function h(tag, attrs) {
  var node = document.createElement(tag);
  Object.keys(attrs || {}).forEach(function (key) {
    var value = attrs[key];
    if (value === null || value === undefined || value === false) { return; }
    if (key === "class") { node.className = value; } else { node.setAttribute(key, value); }
  });
  for (var i = 2; i < arguments.length; i++) { append(node, arguments[i]); }
  return node;
}
function append(node, child) {
  if (child === null || child === undefined || child === false) { return; }
  if (Array.isArray(child)) { child.forEach(function (item) { append(node, item); }); return; }
  node.appendChild(typeof child === "string" || typeof child === "number" ? document.createTextNode(String(child)) : child);
}
function link(route, children, cls) { return h("a", { href: "#/" + route, class: cls }, children); }
/* Only http(s) addresses become links; anything else is shown as text. */
function external(url, label) {
  if (!/^https?:\/\//i.test(url || "")) { return h("span", { class: "mono" }, label || url || ""); }
  return h("a", { href: url, target: "_blank", rel: "noopener noreferrer" }, label || url);
}

/* Search compares text with case and spacing removed. */
function fold(text) { return String(text || "").toLowerCase().replace(/\s+/g, ""); }
/* A short stretch of text around the first match, with the match marked. */
function snippet(text, query) {
  var at = text.toLowerCase().indexOf(query.toLowerCase());
  if (at < 0) { return h("p", null, text.slice(0, 90) + (text.length > 90 ? "…" : "")); }
  var from = Math.max(0, at - 36), to = Math.min(text.length, at + query.length + 60);
  return h("p", null, from ? "…" : "", text.slice(from, at), h("mark", null, text.slice(at, at + query.length)), text.slice(at + query.length, to), to < text.length ? "…" : "");
}
/* A malformed escape in the address bar is shown as typed instead of throwing. */
function safeDecode(text) {
  try { return decodeURIComponent(text); } catch (error) { return text; }
}
