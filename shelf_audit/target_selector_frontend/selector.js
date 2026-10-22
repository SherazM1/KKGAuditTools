/* Streamlit v1 protocol, no external scripts or image requests.
 * touch-action:none is scoped to the image in CSS: browsers must know the
 * gesture policy BEFORE pointerdown or they may cancel a touch drag to pan.
 * No document/body scroll lock is installed. Capture ends on up/cancel.
 */
const surface = document.getElementById('surface');
const photo = document.getElementById('photo');
const box = document.getElementById('box');
const status = document.getElementById('status');
let region = null, drag = null, identity = null, minimum = .01;
function send(type, payload = {}) {
  window.parent.postMessage({isStreamlitMessage: true, type, ...payload}, '*');
}
function height() { send('streamlit:setFrameHeight', {height: document.body.scrollHeight}); }
function paint() {
  box.style.display = region ? 'block' : 'none';
  if (region) Object.assign(box.style, {left:region.x*100+'%', top:region.y*100+'%', width:region.width*100+'%', height:region.height*100+'%'});
}
function publish(value, message) {
  region = value; paint(); status.textContent = message;
  send('streamlit:setComponentValue', {value, dataType:'json'}); height();
}
function point(event) {
  const bounds = surface.getBoundingClientRect();
  return {x:Math.max(0,Math.min(1,(event.clientX-bounds.left)/bounds.width)),
          y:Math.max(0,Math.min(1,(event.clientY-bounds.top)/bounds.height))};
}
function rectangle(a,b) {
  const x = Math.min(a.x,b.x), y = Math.min(a.y,b.y);
  return {x,y,width:Math.min(Math.abs(a.x-b.x),1-x),height:Math.min(Math.abs(a.y-b.y),1-y)};
}
surface.addEventListener('pointerdown', event => {
  if (drag || !event.isPrimary || event.button !== 0 || !photo.complete) return;
  event.preventDefault(); surface.setPointerCapture(event.pointerId);
  drag = {id:event.pointerId, start:point(event), clientX:event.clientX, clientY:event.clientY};
  // Invalidate old findings as soon as their target starts changing.
  publish(null, 'Drag to select; release to finish.');
});
surface.addEventListener('pointermove', event => {
  if (!drag || drag.id !== event.pointerId) return;
  event.preventDefault(); region = rectangle(drag.start,point(event)); paint();
});
surface.addEventListener('pointerup', event => {
  if (!drag || drag.id !== event.pointerId) return;
  event.preventDefault();
  const value = rectangle(drag.start,point(event));
  const large = Math.abs(event.clientX-drag.clientX)>=12 && Math.abs(event.clientY-drag.clientY)>=12
    && value.width>=minimum && value.height>=minimum;
  drag = null; surface.releasePointerCapture(event.pointerId);
  publish(large ? value : null, large ? 'Target selected. Drag again or choose Redraw target to replace it.' : 'Target too small. Drag a larger rectangle.');
});
function cancel(event) {
  if (!drag || drag.id !== event.pointerId) return;
  drag = null; publish(null, 'Selection cancelled. Drag again.');
}
surface.addEventListener('pointercancel', cancel);
surface.addEventListener('lostpointercapture', cancel);
document.getElementById('clear').onclick = () => publish(null, 'Drag across the subject to select a new target.');
document.getElementById('full').onclick = () => publish({x:0,y:0,width:1,height:1}, 'Full image selected.');
window.addEventListener('message', event => {
  if (event.source !== window.parent || event.data.type !== 'streamlit:render') return;
  const args = event.data.args;
  if (identity !== args.identity) { identity = args.identity; region = args.existing || null; drag = null; paint(); }
  minimum = args.min_fraction;
  surface.style.maxWidth = args.source_width+'px';
  if (photo.getAttribute('src') !== args.image) photo.src = args.image;
  height();
});
photo.onload = height;
new ResizeObserver(height).observe(document.body);
send('streamlit:componentReady', {apiVersion:1});
