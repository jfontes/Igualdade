// Igualdade Acreana Nº 2 — comportamento leve das telas (sem dependências)
(function () {
  "use strict";

  const digitos = (v) => (v || "").replace(/\D/g, "");

  const mascaras = {
    cpf(v) {
      v = digitos(v).slice(0, 11);
      return v.replace(/(\d{3})(\d)/, "$1.$2").replace(/(\d{3})(\d)/, "$1.$2").replace(/(\d{3})(\d{1,2})$/, "$1-$2");
    },
    cep(v) {
      v = digitos(v).slice(0, 8);
      return v.length > 5 ? v.slice(0, 5) + "-" + v.slice(5) : v;
    },
    tel(v) {
      v = digitos(v);
      if (v.length > 11 && v.startsWith("55")) v = v.slice(2);  // colou com +55
      v = v.slice(0, 11);
      if (v.length <= 2) return v ? "(" + v : v;
      const meio = v.length === 11 ? 7 : 6;
      return `(${v.slice(0, 2)}) ${v.slice(2, meio)}${v.length > meio ? "-" + v.slice(meio) : ""}`;
    },
  };

  document.querySelectorAll("[data-mascara]").forEach((el) => {
    const fn = mascaras[el.dataset.mascara];
    el.addEventListener("input", () => { el.value = fn(el.value); });
  });

  // Nomes e endereços em maiúsculas (padrão do cadastro)
  document.querySelectorAll("[data-maiusculas]").forEach((el) => {
    el.style.textTransform = "uppercase";
  });

  // Confirmação antes de ações destrutivas
  document.querySelectorAll("form[data-confirmar]").forEach((form) => {
    form.addEventListener("submit", (e) => {
      if (!confirm(form.dataset.confirmar)) e.preventDefault();
    });
  });

  // Busca de endereço pelo CEP (chamadas feitas pelo navegador).
  // Tenta o ViaCEP e, se falhar, o OpenCEP. Se o CEP não existir em nenhum,
  // usa o CEP geral da faixa (XXXXX-000) só para sugerir cidade e UF.
  const cep = document.getElementById("cep");
  if (cep) {
    const status = document.getElementById("cep-status");
    const aviso = (texto, tipo) => {
      status.textContent = texto;
      status.className = "cep-status" + (tipo ? " " + tipo : "");
    };
    const campo = (id) => document.getElementById(id);
    const preencher = (id, valor, sobrescrever = true) => {
      const el = campo(id);
      if (el && valor && (sobrescrever || !el.value.trim())) el.value = valor.toUpperCase();
    };
    const preencherUf = (uf) => {
      const el = campo("estado");
      if (el && uf) el.value = uf.toUpperCase();
    };

    const servicos = [
      (c) => `https://viacep.com.br/ws/${c}/json/`,
      (c) => `https://opencep.com/v1/${c}`,
    ];
    const consultar = async (c) => {
      let falhouRede = true;
      for (const url of servicos) {
        try {
          const resp = await fetch(url(c), { signal: AbortSignal.timeout?.(6000) });
          if (resp.status === 404) { falhouRede = false; continue; }
          if (!resp.ok) continue;
          const d = await resp.json();
          falhouRede = false;
          if (d && !d.erro && !d.error && d.localidade) return d;
        } catch (_) { /* tenta o próximo serviço */ }
      }
      return falhouRede ? undefined : null;  // undefined = sem conexão; null = não existe
    };

    let ultimo = digitos(cep.value);
    const buscar = async () => {
      const valor = digitos(cep.value);
      if (valor.length !== 8) { if (!valor) aviso(""); return; }
      if (valor === ultimo) return;
      ultimo = valor;
      aviso("Buscando endereço…");
      const d = await consultar(valor);
      if (digitos(cep.value) !== valor) return;  // o usuário já mudou o CEP
      if (d) {
        preencher("logradouro", d.logradouro);
        preencher("bairro", d.bairro);
        preencher("cidade", d.localidade);
        preencherUf(d.uf);
        aviso("✓ Endereço preenchido. Confira e informe o número.", "ok");
        campo("numero")?.focus();
        return;
      }
      if (d === undefined) {
        aviso("Sem conexão para buscar o CEP. Preencha o endereço manualmente.", "erro");
        return;
      }
      const geral = valor.slice(0, 5) + "000";
      const g = geral !== valor ? await consultar(geral) : null;
      if (g) {
        preencher("cidade", g.localidade, false);
        preencherUf(g.uf);
        aviso(`CEP não consta na base dos Correios. Cidade sugerida: ${g.localidade}/${g.uf}. Preencha logradouro e bairro.`, "alerta");
      } else {
        aviso("CEP não encontrado. Confira o número ou preencha o endereço manualmente.", "alerta");
      }
      campo("logradouro")?.focus();
    };
    cep.addEventListener("input", buscar);
    cep.addEventListener("change", buscar);  // cobre colar e preenchimento automático do navegador
  }

  // Foto: pré-visualização imediata da imagem escolhida (câmera ou galeria)
  document.querySelectorAll("[data-foto]").forEach((bloco) => {
    const input = bloco.querySelector('input[type="file"]');
    const avatar = bloco.querySelector(".avatar");
    const nome = bloco.querySelector("[data-foto-nome]");
    const remover = bloco.querySelector('input[name="remover_foto"]');
    const original = avatar.innerHTML;
    bloco.querySelector("label.btn").addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); input.click(); }
    });
    input.addEventListener("change", () => {
      const arq = input.files[0];
      if (!arq) { avatar.innerHTML = original; return; }
      if (arq.size > 20 * 1024 * 1024) {
        alert("A foto é grande demais (máximo 20 MB).");
        input.value = "";
        avatar.innerHTML = original;
        return;
      }
      const img = document.createElement("img");
      img.alt = "";
      img.src = URL.createObjectURL(arq);
      avatar.replaceChildren(img);
      nome.textContent = "Nova foto selecionada — será gravada ao salvar.";
      if (remover) remover.checked = false;
    });
    remover?.addEventListener("change", () => {
      if (remover.checked) {
        input.value = "";
        avatar.style.opacity = ".35";
      } else {
        avatar.style.opacity = "";
      }
    });
  });

  // Mostrar/ocultar a senha digitada (ajuda quem tem dificuldade para digitar no celular)
  document.querySelectorAll("[data-mostrar-senha]").forEach((chk) => {
    chk.addEventListener("change", () => {
      chk.form.querySelectorAll('input[name="nova"], input[name="confirma"]').forEach((el) => {
        el.type = chk.checked ? "text" : "password";
      });
    });
  });

  // Evita envio duplicado por toque duplo (ex.: cadastrar o mesmo familiar duas vezes)
  document.querySelectorAll("form[data-uma-vez]").forEach((form) => {
    form.addEventListener("submit", (e) => {
      if (e.defaultPrevented) return;
      if (form.dataset.enviando) { e.preventDefault(); return; }
      form.dataset.enviando = "1";
      setTimeout(() => form.querySelectorAll('button[type="submit"]').forEach((b) => {
        b.disabled = true;
        b.textContent = "Aguarde…";
      }), 0);
    });
  });

  // Caixa de seleção que mostra/oculta um bloco (ex.: motivo do cancelamento da sessão)
  document.querySelectorAll("[data-mostra]").forEach((chk) => {
    const alvo = document.getElementById(chk.dataset.mostra);
    const atualizar = () => {
      alvo?.classList.toggle("oculto", !chk.checked);
      // campo só é obrigatório enquanto aparece (ex.: motivo, quando a sessão está cancelada)
      alvo?.querySelectorAll("[data-obrigatorio-se-visivel]").forEach((el) => { el.required = chk.checked; });
    };
    chk.addEventListener("change", () => { atualizar(); if (chk.checked) alvo?.querySelector("input")?.focus(); });
    atualizar();
  });

  // Botão "Agora": preenche o horário (HH:MM) com a hora do aparelho
  document.querySelectorAll("[data-agora]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const alvo = document.getElementById(btn.dataset.agora);
      const d = new Date();
      if (alvo) alvo.value = String(d.getHours()).padStart(2, "0") + ":" + String(d.getMinutes()).padStart(2, "0");
    });
  });

  // Mantém o mês selecionado visível na barra de meses
  document.querySelector("[data-rolar]")?.scrollIntoView({ inline: "center", block: "nearest" });

  // PWA: permite "Adicionar à tela inicial"
  if ("serviceWorker" in navigator) {
    window.addEventListener("load", () => navigator.serviceWorker.register("/sw.js").catch(() => {}));
  }
})();
