// Lista com rolagem infinita: renderiza em lotes conforme o usuário rola a caixa.
// infiniteList(caixa, itens, item => '<html>', { batch, empty, onRender })
// Retorna { update(novosItens) } que preserva quantos itens já estavam carregados.
function infiniteList(box, items, renderItem, opts = {}) {
  const batch = opts.batch || 20;
  let shown = 0, obs = null;
  box.classList.add('iscroll');
  const draw = keep => {
    if (obs) obs.disconnect();
    const target = Math.min(items.length, Math.max(batch, keep ? shown : 0));
    if (!items.length) { box.innerHTML = opts.empty || '<p class="muted">Nada por aqui.</p>'; shown = 0; return; }
    box.innerHTML = `<div class="iitems ${opts.itemsClass || ''}">${items.slice(0, target).map(renderItem).join('')}</div>
      <div class="isentinel muted">${target < items.length ? 'Carregando mais…' : `${items.length} no total`}</div>`;
    shown = target;
    opts.onRender && opts.onRender(box);
    const sentinel = box.querySelector('.isentinel');
    obs = new IntersectionObserver(entries => {
      if (!entries[0].isIntersecting || shown >= items.length) return;
      const next = items.slice(shown, shown + batch);
      const wrap = box.querySelector('.iitems');
      wrap.insertAdjacentHTML('beforeend', next.map(renderItem).join(''));
      shown += next.length;
      sentinel.textContent = shown < items.length ? 'Carregando mais…' : `${items.length} no total`;
      opts.onRender && opts.onRender(box);
    }, { root: box, rootMargin: '120px' });
    obs.observe(sentinel);
  };
  draw(false);
  return { update(newItems) { const top = box.scrollTop; items = newItems; draw(true); box.scrollTop = top; } };
}
