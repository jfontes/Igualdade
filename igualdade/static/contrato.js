// Parque das Acácias: fotos da vistoria (caseiro), assinatura do contrato (contratante)
// e assinatura padronizada da LOCADORA (Venerável, na configuração do Parque).
(function () {
  "use strict";

  // ------------------------------------------------------------ fotos da vistoria
  // Cada foto é reduzida no aparelho para 1280 px (o tamanho final gravado), ficando com ~150–300 KB,
  // e enviada UMA POR VEZ, com progresso, até 3 tentativas e limite de tempo: na internet do celular
  // um envio grande e único costumava cair no meio. O servidor confirma quantas fotos gravou.
  // Um formulário por tipo de foto (com tipo_id) e um para "Outras fotos".
  const LADO_MAX = 1280;
  const TENTATIVAS_ENVIO = 3;
  const TEMPO_MAX_MS = 90000;
  const reduzirFoto = (arquivo) => new Promise((ok) => {
    const img = new Image();
    const url = URL.createObjectURL(arquivo);
    img.onload = () => {
      const escala = Math.min(1, LADO_MAX / Math.max(img.width, img.height));
      const c = document.createElement("canvas");
      c.width = Math.round(img.width * escala);
      c.height = Math.round(img.height * escala);
      c.getContext("2d").drawImage(img, 0, 0, c.width, c.height);
      URL.revokeObjectURL(url);
      c.toBlob((b) => ok(b || arquivo), "image/jpeg", 0.8);
    };
    img.onerror = () => { URL.revokeObjectURL(url); ok(arquivo); };
    img.src = url;
  });
  // Envia uma foto; resolve com a resposta JSON do servidor ou rejeita (rede, tempo, erro do servidor)
  const enviarUma = (acao, campos, foto, nome, progresso) => new Promise((ok, falha) => {
    const dados = new FormData();
    Object.entries(campos).forEach(([k, v]) => dados.append(k, v));
    dados.append("fotos", foto, nome);
    const xhr = new XMLHttpRequest();
    xhr.open("POST", acao);
    xhr.setRequestHeader("X-Requested-With", "fetch");
    xhr.timeout = TEMPO_MAX_MS;
    xhr.upload.onprogress = (e) => { if (e.lengthComputable) progresso(Math.round((e.loaded / e.total) * 100)); };
    xhr.onload = () => {
      let r = null;
      try { r = JSON.parse(xhr.responseText); } catch (_) { /* página de login: acesso expirou */ }
      if (xhr.status === 200 && r && r.gravadas > 0) { ok(r); return; }
      const e = new Error(r ? r.mensagem || "recusada" : xhr.status === 200 ? "acesso" : String(xhr.status));
      if (r && r.vazio) e.message = "rede";  // a foto não chegou inteira: tenta de novo
      e.definitivo = (Boolean(r) && !r.vazio) || [200, 400, 403, 404].includes(xhr.status) && !r;  // repetir não resolve
      falha(e);
    };
    xhr.onerror = () => falha(new Error("rede"));
    xhr.ontimeout = () => falha(new Error("tempo"));
    xhr.send(dados);
  });
  document.querySelectorAll("[data-fotos-vistoria]").forEach((formFotos) => {
    const status = formFotos.querySelector("[data-fotos-status]")
      || formFotos.closest("li")?.querySelector("[data-fotos-status]") || { textContent: "" };
    const tipo = formFotos.querySelector("[name=tipo_id]");
    let ocupado = false;
    formFotos.querySelectorAll("[data-enviar-fotos]").forEach((input) => {
      input.addEventListener("change", async () => {
        const arquivos = [...input.files];
        input.value = "";
        if (!arquivos.length || ocupado) return;
        if (!window.FormData || !window.XMLHttpRequest) { formFotos.submit(); return; }
        ocupado = true;
        formFotos.querySelectorAll("label.btn").forEach((b) => b.classList.add("desativado"));
        const campos = { csrf_token: formFotos.querySelector("[name=csrf_token]").value };
        if (tipo) campos.tipo_id = tipo.value;
        const n = arquivos.length;
        let enviadas = 0;
        const falhas = [];
        for (let i = 0; i < n; i++) {
          const rotulo = n > 1 ? `foto ${i + 1} de ${n}` : "foto";
          status.textContent = `Preparando ${rotulo}…`;
          const foto = await reduzirFoto(arquivos[i]);
          let ultimoErro = null;
          for (let t = 1; t <= TENTATIVAS_ENVIO; t++) {
            try {
              const nova = t > 1 ? ` (tentativa ${t} de ${TENTATIVAS_ENVIO})` : "";
              await enviarUma(formFotos.action, campos, foto, `foto_${i + 1}.jpg`,
                (p) => { status.textContent = `Enviando ${rotulo}: ${p}%${nova}`; });
              enviadas++;
              ultimoErro = null;
              break;
            } catch (e) {
              ultimoErro = e;
              if (e.definitivo) break;
              await new Promise((r) => setTimeout(r, 1500 * t));
            }
          }
          if (ultimoErro) falhas.push({ i: i + 1, erro: ultimoErro.message });
        }
        ocupado = false;
        formFotos.querySelectorAll("label.btn").forEach((b) => b.classList.remove("desativado"));
        if (!falhas.length) { location.reload(); return; }
        const rede = ["rede", "tempo", "502", "503", "504", "0"];
        const motivo = falhas.some((f) => f.erro === "acesso")
          ? "O acesso expirou. Recarregue a página e entre de novo."
          : falhas.every((f) => rede.includes(f.erro))
            ? "A internet está lenta ou caiu. Tente de novo (de preferência no Wi-Fi)."
            : /^\d+$/.test(falhas[0].erro) ? `Erro no servidor (código ${falhas[0].erro}). Tente de novo.` : falhas[0].erro;
        status.textContent = (enviadas ? `${enviadas} de ${n} foto(s) enviada(s). ` : "")
          + `Não foi possível enviar ${falhas.length > 1 ? falhas.length + " fotos" : "a foto"}. ${motivo}`;
        if (enviadas && status.append) {
          const recarregar = document.createElement("button");
          recarregar.type = "button";
          recarregar.className = "btn sec pequeno";
          recarregar.textContent = "Ver as fotos enviadas";
          recarregar.addEventListener("click", () => location.reload());
          status.append(" ", recarregar);
        }
      });
    });
  });

  // ------------------------------------------------------------ quadro de assinatura (reutilizável)
  // Devolve { pontos(), png(), limpar() }; o traço acompanha o tamanho do quadro na tela.
  const criarQuadro = (quadro) => {
    const ctx = quadro.getContext("2d");
    let tracos = [];
    let atual = null;
    const redesenhar = () => {
      ctx.clearRect(0, 0, quadro.width, quadro.height);
      const r = quadro.getBoundingClientRect();
      tracos.forEach((t) => {
        ctx.beginPath();
        t.forEach(([x, y], i) => (i ? ctx.lineTo(x * r.width, y * r.height) : ctx.moveTo(x * r.width, y * r.height)));
        ctx.stroke();
      });
    };
    const ajustar = () => {
      const r = quadro.getBoundingClientRect();
      const dpr = window.devicePixelRatio || 1;
      quadro.width = Math.round(r.width * dpr);
      quadro.height = Math.round(r.height * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.lineWidth = 2.6; ctx.lineCap = "round"; ctx.lineJoin = "round"; ctx.strokeStyle = "#0b1f5c";
      redesenhar();
    };
    const ponto = (ev) => {
      const r = quadro.getBoundingClientRect();
      return [+((ev.clientX - r.left) / r.width).toFixed(4), +((ev.clientY - r.top) / r.height).toFixed(4)];
    };
    quadro.addEventListener("pointerdown", (ev) => {
      ev.preventDefault();
      quadro.setPointerCapture(ev.pointerId);
      atual = [ponto(ev)];
      tracos.push(atual);
    });
    quadro.addEventListener("pointermove", (ev) => {
      if (!atual) return;
      ev.preventDefault();
      atual.push(ponto(ev));
      redesenhar();
    });
    const soltar = () => { atual = null; };
    quadro.addEventListener("pointerup", soltar);
    quadro.addEventListener("pointercancel", soltar);
    window.addEventListener("resize", ajustar);
    ajustar();
    return {
      pontos: () => tracos.reduce((n, t) => n + t.length, 0),
      png: () => quadro.toDataURL("image/png"),
      limpar: () => { tracos = []; redesenhar(); },
    };
  };

  // assinatura padronizada da LOCADORA (Venerável)
  const formLocadora = document.querySelector("[data-assinatura-locadora]");
  if (formLocadora) {
    const q = criarQuadro(formLocadora.querySelector("[data-quadro]"));
    const erroQ = formLocadora.querySelector("[data-erro-quadro]");
    formLocadora.querySelector("[data-limpar-quadro]").addEventListener("click", () => { q.limpar(); erroQ.textContent = ""; });
    formLocadora.addEventListener("submit", (ev) => {
      if (q.pontos() < 15) { ev.preventDefault(); erroQ.textContent = "Faça a assinatura no quadro."; return; }
      formLocadora.querySelector("[name=assinatura]").value = q.png();
    });
  }

  // ------------------------------------------------------------ assinatura
  const form = document.querySelector("[data-assinatura]");
  if (!form) return;
  const erro = form.querySelector("[data-erro-assinatura]");
  const campo = (nome) => form.querySelector(`[name="${nome}"]`);

  // selfie em tempo real (câmera frontal; sem galeria)
  const video = form.querySelector("[data-video]");
  const previa = form.querySelector("[data-selfie-previa]");
  const aviso = form.querySelector("[data-camera-aviso]");
  const bAbrir = form.querySelector("[data-abrir-camera]");
  const bTirar = form.querySelector("[data-tirar-foto]");
  const bRefazer = form.querySelector("[data-refazer-foto]");
  let fluxo = null;
  const pararCamera = () => { if (fluxo) { fluxo.getTracks().forEach((t) => t.stop()); fluxo = null; } };
  const abrirCamera = async () => {
    erro.textContent = "";
    if (!window.isSecureContext) {
      // câmera só funciona em endereço seguro (https); acontece no teste local por http://IP-DO-PC
      aviso.textContent = "A câmera só funciona em endereço seguro (https). Abra o link enviado pelo sistema, que começa com https://.";
      return;
    }
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      aviso.textContent = "Este navegador não permite usar a câmera. Abra o link no Chrome ou no Safari do celular.";
      return;
    }
    try {
      fluxo = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "user", width: { ideal: 960 } }, audio: false });
      video.srcObject = fluxo;
      video.hidden = false; previa.hidden = true; aviso.textContent = "";
      bAbrir.hidden = true; bTirar.hidden = false; bRefazer.hidden = true;
      campo("selfie").value = "";
    } catch (_) {
      aviso.textContent = "Não foi possível abrir a câmera. Permita o acesso à câmera nas configurações do navegador e tente de novo.";
    }
  };
  bAbrir.addEventListener("click", abrirCamera);
  bRefazer.addEventListener("click", abrirCamera);
  bTirar.addEventListener("click", () => {
    if (!video.videoWidth) return;
    const escala = Math.min(1, 640 / video.videoWidth);
    const c = document.createElement("canvas");
    c.width = Math.round(video.videoWidth * escala);
    c.height = Math.round(video.videoHeight * escala);
    c.getContext("2d").drawImage(video, 0, 0, c.width, c.height);
    const dados = c.toDataURL("image/jpeg", 0.85);
    campo("selfie").value = dados;
    previa.src = dados; previa.hidden = false; video.hidden = true;
    pararCamera();
    bTirar.hidden = true; bRefazer.hidden = false;
  });
  window.addEventListener("pagehide", pararCamera);

  // assinatura manuscrita (traço com o dedo); PNG transparente + coordenadas
  const quadro = form.querySelector("[data-quadro]");
  const ctx = quadro.getContext("2d");
  let tracos = [];
  let atual = null;
  const ajustar = () => {
    const r = quadro.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    quadro.width = Math.round(r.width * dpr);
    quadro.height = Math.round(r.height * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.lineWidth = 2.6; ctx.lineCap = "round"; ctx.lineJoin = "round"; ctx.strokeStyle = "#0b1f5c";
    redesenhar();
  };
  const redesenhar = () => {
    ctx.clearRect(0, 0, quadro.width, quadro.height);
    const r = quadro.getBoundingClientRect();
    tracos.forEach((t) => {
      ctx.beginPath();
      t.forEach(([x, y], i) => (i ? ctx.lineTo(x * r.width, y * r.height) : ctx.moveTo(x * r.width, y * r.height)));
      ctx.stroke();
    });
  };
  const ponto = (ev) => {
    const r = quadro.getBoundingClientRect();
    return [+((ev.clientX - r.left) / r.width).toFixed(4), +((ev.clientY - r.top) / r.height).toFixed(4), Date.now()];
  };
  quadro.addEventListener("pointerdown", (ev) => {
    ev.preventDefault();
    quadro.setPointerCapture(ev.pointerId);
    atual = [ponto(ev)];
    tracos.push(atual);
  });
  quadro.addEventListener("pointermove", (ev) => {
    if (!atual) return;
    ev.preventDefault();
    atual.push(ponto(ev));
    redesenhar();
  });
  const soltar = () => { atual = null; };
  quadro.addEventListener("pointerup", soltar);
  quadro.addEventListener("pointercancel", soltar);
  form.querySelector("[data-limpar-assinatura]").addEventListener("click", () => { tracos = []; redesenhar(); });
  window.addEventListener("resize", ajustar);
  ajustar();

  // geolocalização opcional (só com o consentimento marcado)
  form.querySelector("[data-geo]").addEventListener("change", (ev) => {
    campo("geolocalizacao").value = "";
    if (!ev.target.checked || !navigator.geolocation) return;
    navigator.geolocation.getCurrentPosition(
      (p) => { campo("geolocalizacao").value =
        `${p.coords.latitude.toFixed(5)}, ${p.coords.longitude.toFixed(5)} (±${Math.round(p.coords.accuracy)} m)`; },
      () => { ev.target.checked = false; erro.textContent = "Não foi possível obter a localização (ela é opcional)."; },
      { enableHighAccuracy: true, timeout: 10000 });
  });

  form.addEventListener("submit", (ev) => {
    const pontos = tracos.reduce((n, t) => n + t.length, 0);
    let msg = "";
    if (!campo("selfie").value) msg = "Tire a foto do rosto antes de assinar.";
    else if (pontos < 15) msg = "Faça a sua assinatura no quadro.";
    else if (!campo("li_contrato").checked || !campo("consentimento").checked) msg = "Marque as duas confirmações.";
    if (msg) { ev.preventDefault(); erro.textContent = msg; return; }
    campo("assinatura").value = quadro.toDataURL("image/png");
    campo("traco").value = JSON.stringify(tracos);
    const b = form.querySelector("[data-botao-assinar]");
    b.disabled = true; b.textContent = "Assinando…";
  });
})();
