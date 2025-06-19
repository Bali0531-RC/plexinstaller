export default {
    async fetch(request, env, ctx) {
      const url = new URL(request.url);
      let path = url.pathname;
  
      // Főoldal
      if (path === "/" || path === "/index.html") {
        return new Response(await STATIC_INDEX, { headers: { "content-type": "text/html; charset=utf-8" } });
      }
      // Guide oldal
      if (path === "/guide" || path === "/guide/" || path === "/guide/index.html") {
        return new Response(await STATIC_GUIDE, { headers: { "content-type": "text/html; charset=utf-8" } });
      }
      // install.sh
      if (path === "/install.sh") {
        return new Response(await STATIC_INSTALL, { headers: { "content-type": "text/x-sh; charset=utf-8" } });
      }
      // beta.sh
      if (path === "/beta.sh") {
        return new Response(await STATIC_BETA, { headers: { "content-type": "text/x-sh; charset=utf-8" } });
      }
      // 404
      return new Response("404 Not Found", { status: 404 });
    }
  }
  
  // Ezeket a sorokat a build parancs fogja generálni:
  const STATIC_INDEX = `__INDEX_HTML__`;
  const STATIC_GUIDE = `__GUIDE_HTML__`;
  const STATIC_INSTALL = `__INSTALL_SH__`;
  const STATIC_BETA = `__BETA_SH__`;