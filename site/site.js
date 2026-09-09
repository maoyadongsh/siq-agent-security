document.querySelectorAll('[data-copy]').forEach((button) => {
  if (!navigator.clipboard) return;
  button.hidden = false;
  button.addEventListener('click', async () => {
    const target = document.querySelector(button.dataset.copy);
    const status = document.getElementById('copy-status');
    if (!target) return;
    try {
      await navigator.clipboard.writeText(target.textContent);
      button.textContent = '已复制';
      status.textContent = '命令已复制到剪贴板';
    } catch {
      button.textContent = '请手动复制';
      status.textContent = '无法访问剪贴板，请选中代码手动复制';
      target.focus();
    }
    window.setTimeout(() => { button.textContent = '复制命令'; }, 2000);
  });
});
