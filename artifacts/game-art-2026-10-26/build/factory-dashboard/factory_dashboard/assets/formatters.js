'use strict';
// Pure presentation functions also run in Node checks without a mocked browser.
const FactoryFormat = (() => {
 const money = n => typeof n==='number' ? new Intl.NumberFormat('en-US',{style:'currency',currency:'USD',maximumFractionDigits:4}).format(n) : 'unavailable';
 function costLines(u){
  const total=u.sessions??0;
  return [
   `Actual: ${money(u.actual_usd)} · ${u.actual_known_sessions??0}/${total} sessions`,
   `Estimates: ${money(u.estimated_usd)} · ${u.estimated_known_sessions??0}/${total} sessions (separate from actual)`,
   `Included: ${u.included_sessions??0}/${total} sessions · no dollar charge inferred`,
   `Unknown actual: ${u.unknown_actual_sessions??0}/${total} non-included sessions`
  ];
 }
 return {money,costLines};
})();
if(typeof module!=='undefined'&&module.exports)module.exports=FactoryFormat;
