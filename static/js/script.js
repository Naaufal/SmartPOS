document.addEventListener('DOMContentLoaded', () => {
    const buttons = document.querySelectorAll('.product-choice');
    const list = document.querySelector('#cart-items');
    const subtotalEl = document.querySelector('#cart-subtotal');
    const totalEl = document.querySelector('#cart-total');
    const dataEl = document.querySelector('#cart-data');
    const discountInput = document.querySelector('#discount');
    const paymentInput = document.querySelector('#payment');
    const changeEl = document.querySelector('#change-preview');
    const checkoutForm = document.querySelector('#checkout-form');

    if (!buttons.length || !list || !checkoutForm) return;

    const cart = {};
    const money = (n) => 'Rp' + Number(n || 0).toLocaleString('id-ID');

    function updateSummary(subtotal) {
        const rawDiscount = Number(discountInput ? discountInput.value : 0);
        const discount = Number.isFinite(rawDiscount) && rawDiscount > 0 ? Math.floor(rawDiscount) : 0;
        const clampedDiscount = Math.min(discount, subtotal);
        const total = Math.max(0, subtotal - clampedDiscount);

        if (subtotalEl) subtotalEl.textContent = money(subtotal);
        if (totalEl) totalEl.textContent = money(total);

        if (changeEl && paymentInput) {
            const payment = Number(paymentInput.value || 0);
            if (paymentInput.value === '') {
                changeEl.textContent = 'Rp0';
                changeEl.classList.remove('text-danger', 'text-success');
            } else if (payment < total) {
                changeEl.textContent = 'Kurang ' + money(total - payment);
                changeEl.classList.add('text-danger');
                changeEl.classList.remove('text-success');
            } else {
                changeEl.textContent = money(payment - total);
                changeEl.classList.add('text-success');
                changeEl.classList.remove('text-danger');
            }
        }
    }

    function draw() {
        list.innerHTML = '';
        let subtotal = 0;
        const items = Object.values(cart);

        items.forEach((item) => {
            subtotal += item.price * item.qty;
            const row = document.createElement('div');
            row.className = 'cart-line d-flex justify-content-between align-items-center gap-2';
            row.innerHTML = `
                <div class="flex-grow-1">
                    <div class="fw-semibold">${item.name}</div>
                    <small class="text-muted font-mono-num">${money(item.price)} &times; ${item.qty} = ${money(item.price * item.qty)}</small>
                </div>
                <div class="btn-group btn-group-sm" role="group">
                    <button type="button" class="btn btn-outline-secondary" data-dec="${item.id}" title="Kurangi">&minus;</button>
                    <button type="button" class="btn btn-outline-secondary" data-inc="${item.id}" title="Tambah">+</button>
                    <button type="button" class="btn btn-outline-danger" data-remove="${item.id}" title="Hapus">&times;</button>
                </div>
            `;
            list.append(row);
        });

        if (!items.length) {
            list.innerHTML = '<div class="empty-state py-3"><i class="bi bi-basket2"></i><span>Keranjang masih kosong. Klik produk di sebelah kiri.</span></div>';
        }

        dataEl.value = items.map((i) => `${i.id}:${i.qty}`).join(',');
        updateSummary(subtotal);
    }

    buttons.forEach((btn) => {
        btn.addEventListener('click', () => {
            const id = btn.dataset.id;
            if (!cart[id]) {
                cart[id] = {
                    id,
                    name: btn.dataset.name,
                    price: Number(btn.dataset.price),
                    qty: 0,
                    stock: Number(btn.dataset.stock),
                };
            }
            if (cart[id].qty < cart[id].stock) {
                cart[id].qty++;
            }
            draw();
        });
    });

    list.addEventListener('click', (e) => {
        const target = e.target.closest('button');
        if (!target) return;

        const incId = target.dataset.inc;
        const decId = target.dataset.dec;
        const removeId = target.dataset.remove;

        if (incId && cart[incId]) {
            if (cart[incId].qty < cart[incId].stock) cart[incId].qty++;
            draw();
        } else if (decId && cart[decId]) {
            cart[decId].qty--;
            if (cart[decId].qty <= 0) delete cart[decId];
            draw();
        } else if (removeId && cart[removeId]) {
            delete cart[removeId];
            draw();
        }
    });

    const getSubtotal = () => Object.values(cart).reduce((acc, item) => acc + item.price * item.qty, 0);

    if (discountInput) {
        discountInput.addEventListener('input', () => updateSummary(getSubtotal()));
    }
    if (paymentInput) {
        paymentInput.addEventListener('input', () => updateSummary(getSubtotal()));
    }

    checkoutForm.addEventListener('submit', (e) => {
        if (!Object.keys(cart).length) {
            e.preventDefault();
            alert('Keranjang masih kosong.');
        }
    });

    draw();
});
