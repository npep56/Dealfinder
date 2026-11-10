// Stand-in for the dashboard runtime (dash.loader / dash.calc / dash.draw / dash.data), enough to
// run the page offline in a browser with made-up data. Not the real runtime: no live queries, no Sources panel.
// Minimal stand-in for the dashboard runtime, enough to run the page offline.
window.__errors = [];
window.dash = {
  colors: ['#2f6fdf', '#e07b1a', '#1d9a6c', '#8a4fd8', '#d43f7a'],
  _l: {}, _c: {}, _d: {}, _draws: {}, _on: [],
  loader(id, o) { this._l[id] = o.fn; },
  calc(id, o) { this._c[id] = o; },
  draw(name, fn) { (this._draws[name] ||= []).push(fn); },
  onData(fn) { this._on.push(fn); },
  data(id) { return this._d[id] || { status: 'missing', data: [] }; },
  params() { return {}; }, setParams() {}, resetParams() {}, setLink() {}, refresh() {},
};
window.__run = async (fixtures) => {
  const D = window.dash;
  for (const [id, raw] of Object.entries(fixtures)) {
    try {
      let out = D._l[id] ? await D._l[id]({ answer: raw, read: {}, args: {} }) : raw;
      const rows = Array.isArray(out) ? out : out.data;
      D._d[id] = { status: 'ok', data: rows, columns: out.columns };
    } catch (e) { __errors.push('loader ' + id + ': ' + e.message); D._d[id] = { status: 'error', data: [] }; }
  }
  const pending = Object.keys(D._c);
  for (let guard = 0; pending.length && guard < 50; guard++) {
    for (const id of [...pending]) {
      const c = D._c[id];
      if (!c.inputs.every((i) => D._d[i])) continue;
      try { D._d[id] = { status: 'ok', data: c.fn(...c.inputs.map((i) => D._d[i].data)) }; }
      catch (e) { __errors.push('calc ' + id + ': ' + e.message); D._d[id] = { status: 'error', data: null }; }
      pending.splice(pending.indexOf(id), 1);
    }
  }
  if (pending.length) __errors.push('calcs never ran (missing inputs): ' + pending.join(', '));
  for (const fn of D._on) { try { fn(); } catch (e) { __errors.push('onData: ' + e.message); } }
  const used = new Set();
  for (const el of document.querySelectorAll('[data-draw]')) {
    const name = el.dataset.draw; used.add(name);
    const fns = D._draws[name];
    if (!fns) { __errors.push('no drawing for data-draw="' + name + '"'); continue; }
    for (const f of fns) { try { typeof f === 'function' ? f(el) : (f.update || (() => {}))(el, f.mount && f.mount(el)); } catch (e) { __errors.push('draw ' + name + ': ' + e.message); } }
  }
  for (const n of Object.keys(D._draws)) if (!used.has(n)) __errors.push('drawing with no element: ' + n);
  const marks = [...document.querySelectorAll('[data-source]')].map((e) => e.dataset.source.split(' ')).flat();
  for (const s of new Set(marks)) if (!D._d[s]) __errors.push('mark names unknown source: ' + s);
  return __errors;
};
