// Dhingani Investment - front-end helpers
let cart = [];

function formatUsd(n) {
  const v = Number(n) || 0;
  const sign = v < 0 ? '-' : '';
  return `${sign}$${Math.abs(v).toFixed(2)}`;
}

function addToCart(id, name, price, stock) {
  const existing = cart.find(i => i.product_id === id);
  if (existing) {
    if (existing.quantity >= stock) { alert('No more stock for ' + name); return; }
    existing.quantity += 1;
  } else {
    if (stock <= 0) { alert('No stock for ' + name); return; }
    cart.push({ product_id: id, name, price, quantity: 1, stock });
  }
  renderCart();
}

function changeQty(id, delta) {
  const it = cart.find(i => i.product_id === id);
  if (!it) return;
  it.quantity += delta;
  if (it.quantity <= 0) cart = cart.filter(i => i.product_id !== id);
  else if (it.quantity > it.stock) it.quantity = it.stock;
  renderCart();
}

function renderCart() {
  const t = document.getElementById('cart-table');
  if (!t) return;
  let html = '<tr><th>Item</th><th>Qty</th><th>Price</th><th></th></tr>';
  let subtotal = 0;
  cart.forEach(i => {
    subtotal += i.price * i.quantity;
    html += `<tr><td>${escapeHtml(i.name)}</td>`
      + `<td><button type="button" class="ghost sm" onclick="changeQty(${i.product_id},-1)">-</button> `
      + `${i.quantity} `
      + `<button type="button" class="ghost sm" onclick="changeQty(${i.product_id},1)">+</button></td>`
      + `<td>${formatUsd(i.price * i.quantity)}</td>`
      + `<td><button type="button" class="danger sm" onclick="changeQty(${i.product_id},-999)">x</button></td></tr>`;
  });
  t.innerHTML = html;

  const { discount, tax, total } = computeTotal(subtotal);
  setText('sum-subtotal', formatUsd(subtotal));
  setText('sum-discount', formatUsd(discount));
  setText('sum-tax', formatUsd(tax));
  setText('cart-total', formatUsd(total));
  updateChangeDue(total);
}

function computeTotal(subtotal) {
  const discountInput = document.getElementById('discount-input');
  const discount = Math.min(subtotal, Math.max(0, parseFloat(discountInput && discountInput.value) || 0));
  const taxRate = typeof TAX_RATE !== 'undefined' ? TAX_RATE : 0;
  const taxable = Math.max(0, subtotal - discount);
  const tax = taxable * taxRate;
  return { discount, tax, total: taxable + tax };
}

function updateChangeDue(total) {
  const row = document.getElementById('change-row');
  const paymentSelect = document.getElementById('payment-method');
  const tenderedInput = document.getElementById('cash-tendered');
  if (!row || !paymentSelect || !tenderedInput) return;

  if (paymentSelect.value !== 'cash' || !tenderedInput.value) {
    row.hidden = true;
    return;
  }
  const tendered = parseFloat(tenderedInput.value) || 0;
  const change = tendered - total;
  row.hidden = false;
  const changeEl = document.getElementById('sum-change');
  changeEl.textContent = change < 0 ? `Short ${formatUsd(-change)}` : formatUsd(change);
  changeEl.className = change < 0 ? 'bad-t' : 'good-t';
}

function setText(id, val) {
  const el = document.getElementById(id);
  if (el) el.textContent = val;
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[c]));
}

async function checkout() {
  if (!cart.length) { alert('Cart is empty'); return; }
  const discountInput = document.getElementById('discount-input');
  const paymentSelect = document.getElementById('payment-method');
  const mobileInput = document.getElementById('mobile-number');
  const tenderedInput = document.getElementById('cash-tendered');
  const paymentMethod = (paymentSelect && paymentSelect.value) || 'cash';
  const status = document.getElementById('sale-status');

  if (paymentMethod === 'cash') {
    const subtotal = cart.reduce((sum, i) => sum + i.price * i.quantity, 0);
    const { total } = computeTotal(subtotal);
    const tendered = parseFloat(tenderedInput && tenderedInput.value) || 0;
    if (tendered < total) {
      status.textContent = `Cash tendered (${formatUsd(tendered)}) is less than the total (${formatUsd(total)}).`;
      return;
    }
  }

  const btn = document.getElementById('checkout-btn');
  btn.disabled = true;

  const res = await fetch('/api/checkout', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      items: cart.map(i => ({ product_id: i.product_id, quantity: i.quantity })),
      discount_amount: parseFloat(discountInput && discountInput.value) || 0,
      payment_method: paymentMethod,
      mobile_number: (mobileInput && mobileInput.value) || '',
    })
  });
  const data = await res.json();

  if (!data.ok) {
    status.textContent = 'Error: ' + (data.error || 'unknown');
    btn.disabled = false;
    return;
  }

  if (data.pending && data.redirect_url) {
    // Card: hand off to Paynow's hosted checkout page.
    status.textContent = 'Redirecting to Paynow to complete payment…';
    cart = []; renderCart();
    window.location.href = data.redirect_url;
    return;
  }

  if (data.pending && data.instructions) {
    // EcoCash/OneMoney: customer authorizes on their phone, we poll.
    status.textContent = data.instructions;
    cart = []; renderCart();
    setTimeout(() => { window.location.href = '/sales/' + data.sale_id + '/receipt'; }, 1200);
    return;
  }

  let m = `Sale #${data.sale_id} complete. Total ${formatUsd(data.total)}, profit ${formatUsd(data.profit)}.`;
  if (paymentMethod === 'cash' && tenderedInput && tenderedInput.value) {
    const change = (parseFloat(tenderedInput.value) || 0) - data.total;
    m += ` Change due: ${formatUsd(change)}.`;
  }
  if (data.low_stock_alerts && data.low_stock_alerts.length)
    m += ' Low-stock alert sent for: ' + data.low_stock_alerts.join(', ');
  status.textContent = m;
  cart = [];
  if (tenderedInput) tenderedInput.value = '';
  renderCart();
  setTimeout(() => { window.location.href = '/sales/' + data.sale_id + '/receipt'; }, 900);
  btn.disabled = false;
}

function togglePaymentExtras() {
  const paymentSelect = document.getElementById('payment-method');
  const mobileField = document.getElementById('mobile-number-field');
  const cashField = document.getElementById('cash-tendered-field');
  if (!paymentSelect || !mobileField || !cashField) return;
  const needsMobile = paymentSelect.value === 'ecocash' || paymentSelect.value === 'onemoney';
  mobileField.hidden = !needsMobile;
  cashField.hidden = paymentSelect.value !== 'cash';
  renderCart();
}

// Receipt page: poll our own /payments/<id>/status (which itself polls
// Paynow) until the sale settles, then reload to show the final receipt.
let __pollTimer = null;
async function checkPaymentStatus(saleId, manual) {
  const msg = document.getElementById('payment-wait-msg');
  try {
    const res = await fetch('/payments/' + saleId + '/status');
    const data = await res.json();
    if (data.status === 'completed' || data.status === 'failed') {
      clearTimeout(__pollTimer);
      window.location.reload();
      return;
    }
    if (manual && msg) {
      msg.textContent = data.error
        ? 'Still waiting… (' + data.error + ')'
        : 'Still waiting for payment confirmation…';
    }
  } catch (err) {
    if (manual && msg) msg.textContent = 'Could not check payment status.';
  }
}

function pollPaymentStatus(saleId) {
  let attempts = 0;
  const tick = async () => {
    attempts += 1;
    await checkPaymentStatus(saleId, false);
    if (attempts < 40) __pollTimer = setTimeout(tick, 3000);
  };
  __pollTimer = setTimeout(tick, 3000);
}

// Barcode scanning: a hardware scanner types the code then sends Enter.
function initBarcodeInput() {
  const input = document.getElementById('barcode-input');
  if (!input) return;
  input.addEventListener('keydown', e => {
    if (e.key === 'Enter' || e.keyCode === 13 || e.which === 13) {
      e.preventDefault();
      scanBarcode();
    }
  });
}

async function scanBarcode() {
  const input = document.getElementById('barcode-input');
  if (!input) return;
  const code = input.value.trim();
  if (!code) return;
  const status = document.getElementById('sale-status');
  try {
    const res = await fetch('/api/products/barcode/' + encodeURIComponent(code));
    if (!res.ok) {
      if (status) status.textContent = 'No product found for barcode ' + code;
      input.select();
      return;
    }
    const p = await res.json();
    addToCart(p.id, p.name, p.sell_price, p.quantity);
    if (status) status.textContent = '';
  } catch (err) {
    if (status) status.textContent = 'Barcode lookup failed.';
  }
  input.value = '';
  input.focus();
}

function initProductButtons() {
  document.querySelectorAll('.prod-btn[data-id]').forEach(btn => {
    btn.addEventListener('click', () => {
      addToCart(
        Number(btn.dataset.id),
        btn.dataset.name,
        parseFloat(btn.dataset.price),
        Number(btn.dataset.stock)
      );
    });
  });
}

document.addEventListener('DOMContentLoaded', () => {
  initBarcodeInput();
  initReceiveBarcodeInput();
  initProductButtons();
  initEditButtons();
  togglePaymentExtras();
  renderCart();
});

// Products form
function editProduct(p) {
  document.getElementById('f-id').value = p.id;
  document.getElementById('f-sku').value = p.sku;
  document.getElementById('f-barcode').value = p.barcode || '';
  document.getElementById('f-name').value = p.name;
  document.getElementById('f-category').value = p.category;
  document.getElementById('f-cost').value = p.cost_price;
  document.getElementById('f-sell').value = p.sell_price;
  document.getElementById('f-qty').value = '';
  window.scrollTo({ top: 0, behavior: 'smooth' });
}
function resetForm() {
  ['f-id', 'f-sku', 'f-barcode', 'f-name', 'f-category', 'f-cost', 'f-sell', 'f-qty']
    .forEach(id => { const el = document.getElementById(id); if (el) el.value = ''; });
}

// Receive stock by barcode: scan a known product to bump its quantity,
// or an unknown one to pre-fill the add-product form above.
let __receiveProduct = null;

function initReceiveBarcodeInput() {
  const input = document.getElementById('receive-barcode-input');
  if (!input) return;
  input.addEventListener('keydown', e => {
    if (e.key === 'Enter' || e.keyCode === 13 || e.which === 13) {
      e.preventDefault();
      scanReceiveBarcode();
    }
  });
}

async function scanReceiveBarcode() {
  const input = document.getElementById('receive-barcode-input');
  if (!input) return;
  const code = input.value.trim();
  if (!code) return;
  const status = document.getElementById('receive-status');
  const panel = document.getElementById('receive-panel');
  status.textContent = '';

  try {
    const res = await fetch('/api/products/barcode/' + encodeURIComponent(code));
    if (!res.ok) {
      panel.hidden = true;
      __receiveProduct = null;
      resetForm();
      document.getElementById('f-barcode').value = code;
      window.scrollTo({ top: 0, behavior: 'smooth' });
      document.getElementById('f-name').focus();
      status.textContent = `No product has barcode ${code} yet — fill in its details above to add it.`;
      input.value = '';
      return;
    }
    const p = await res.json();
    __receiveProduct = p;
    document.getElementById('receive-product-name').textContent = p.name;
    document.getElementById('receive-current-qty').textContent = p.quantity;
    const qtyInput = document.getElementById('receive-qty');
    qtyInput.value = 1;
    panel.hidden = false;
    qtyInput.focus();
    qtyInput.select();
  } catch (err) {
    status.textContent = 'Lookup failed.';
  }
  input.value = '';
}

async function confirmReceive() {
  if (!__receiveProduct) return;
  const qtyInput = document.getElementById('receive-qty');
  const qty = parseInt(qtyInput.value, 10);
  const status = document.getElementById('receive-status');
  if (!qty || qty <= 0) { status.textContent = 'Enter a quantity greater than 0.'; return; }

  const fd = new FormData();
  fd.append('delta', qty);
  fd.append('reason', 'received');
  fd.append('note', 'Received via barcode scan');

  const res = await fetch(`/products/${__receiveProduct.id}/adjust`, {
    method: 'POST', body: fd, headers: { 'X-Requested-With': 'fetch' },
  });
  if (!res.ok) { status.textContent = 'Could not record receipt.'; return; }

  const newQty = __receiveProduct.quantity + qty;
  status.textContent = `Received ${qty} × ${__receiveProduct.name}. New stock: ${newQty}. `
    + `Scan the next item, or reload the page to see it reflected in the table below.`;
  cancelReceive();
  document.getElementById('receive-barcode-input').focus();
}

function cancelReceive() {
  __receiveProduct = null;
  document.getElementById('receive-panel').hidden = true;
}
function initEditButtons() {
  document.querySelectorAll('.edit-btn[data-id]').forEach(btn => {
    btn.addEventListener('click', () => {
      editProduct({
        id: btn.dataset.id,
        sku: btn.dataset.sku,
        barcode: btn.dataset.barcode,
        name: btn.dataset.name,
        category: btn.dataset.category,
        cost_price: btn.dataset.cost,
        sell_price: btn.dataset.sell,
      });
    });
  });
}

// Dashboard actions
async function sendDigest() {
  const s = document.getElementById('action-status');
  s.textContent = 'Sending digest...';
  const r = await fetch('/api/send-digest', { method: 'POST' });
  await r.json();
  s.textContent = 'Digest sent to admin (see Reports > Notification log).';
}
async function checkStock() {
  const s = document.getElementById('action-status');
  s.textContent = 'Checking...';
  const r = await fetch('/api/check-stock', { method: 'POST' });
  const d = await r.json();
  s.textContent = d.alerted.length
    ? 'Alerts sent for: ' + d.alerted.join(', ')
    : 'No low-stock products.';
}
