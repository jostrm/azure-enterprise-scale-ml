(function () {
    if (window.top !== window) return;
    var url = new URL(window.location.href);
    var embedded = url.searchParams.get('host') === 'esaif-maui' && window.chrome && window.chrome.webview;
    var browser = !url.searchParams.has('host') && url.searchParams.get('layout') !== 'legacy';
    var loopback = url.protocol === 'http:' && ['localhost', '127.0.0.1', '[::1]'].indexOf(url.hostname) !== -1;
    if ((url.protocol !== 'https:' && !(browser && loopback)) || url.pathname !== '/' || (!embedded && !browser)) return;
    if (document.getElementById('esaif-maui-layout-script')) return;
    var script = document.createElement('script');
    script.id = 'esaif-maui-layout-script';
    script.src = '/static/esaif-maui-layout.js';
    script.onerror = function () {
        console.error('Agent Chat presentation resource could not load; original controls remain available.');
    };
    document.head.appendChild(script);
})();
