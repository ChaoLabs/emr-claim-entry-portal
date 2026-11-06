/* Small progressive enhancements; server navigation and submissions need no JS. */
document.addEventListener('click', function (event) {
    if (event.target.closest('[data-print]')) window.print();
    const tab = event.target.closest('[data-document-tab]');
    if (!tab) return;
    const container = tab.closest('[data-document-view]');
    if (!container) return;
    container.querySelectorAll('[data-document-tab]').forEach(button => {
        button.setAttribute('aria-selected', String(button === tab));
        button.tabIndex = button === tab ? 0 : -1;
    });
    container.querySelectorAll('[data-document-panel]').forEach(panel => {
        panel.hidden = panel.id !== tab.getAttribute('aria-controls');
    });
});
document.addEventListener('keydown', function (event) {
    const tab = event.target.closest('[data-document-tab]');
    if (!tab || !['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
    const tabs = Array.from(tab.closest('[role="tablist"]').querySelectorAll('[data-document-tab]'));
    let index = tabs.indexOf(tab);
    if (event.key === 'Home') index = 0;
    else if (event.key === 'End') index = tabs.length - 1;
    else index = (index + (event.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length;
    event.preventDefault();
    tabs[index].focus();
    tabs[index].click();
});
document.querySelectorAll('[data-document-view]').forEach(container => {
    container.querySelector('[data-document-tab][aria-selected="true"]')?.click();
    container.querySelector('[role="tablist"]')?.removeAttribute('hidden');
});
