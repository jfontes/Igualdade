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
      const botoes = [...form.querySelectorAll('button[type="submit"]')];
      setTimeout(() => botoes.forEach((b) => {
        if (b.disabled) return;  // já estava desativado (ex.: modelo ausente): não mexe
        b.dataset.texto = b.innerHTML;
        b.disabled = true;
        b.textContent = "Aguarde…";
      }), 0);
      // Se a página não for trocada (ex.: download do .docx), libera os botões de novo
      setTimeout(() => liberar(form), 4000);
    });
  });
  function liberar(form) {
    delete form.dataset.enviando;
    form.querySelectorAll('button[type="submit"][data-texto]').forEach((b) => {
      b.disabled = false;
      b.innerHTML = b.dataset.texto;
      delete b.dataset.texto;
    });
  }
  // Voltar com o botão "voltar" do navegador também libera
  window.addEventListener("pageshow", () => document.querySelectorAll("form[data-uma-vez]").forEach(liberar));

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
  const horaAgora = () => {
    const d = new Date();
    return String(d.getHours()).padStart(2, "0") + ":" + String(d.getMinutes()).padStart(2, "0");
  };
  document.querySelectorAll("[data-agora]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const alvo = document.getElementById(btn.dataset.agora);
      if (alvo) { alvo.value = horaAgora(); alvo.dispatchEvent(new Event("change", { bubbles: true })); }
    });
  });

  // Salvamento automático (balaústre): a cada N segundos, ao alterar um campo e ao sair da página.
  // O campo marcado com data-hora-automatica recebe a hora atual a cada ciclo, até ser editado à mão.
  document.querySelectorAll("form[data-autosave]").forEach((form) => {
    const url = form.dataset.autosave;
    const intervalo = (Number(form.dataset.intervalo) || 30) * 1000;
    const avisos = document.querySelectorAll("[data-autosave-status]");
    const horaAuto = form.querySelector("[data-hora-automatica]");
    const serializar = () => new URLSearchParams(new FormData(form)).toString();
    let ultimo = serializar();
    let salvando = false;
    let editadaAMao = false;
    const aviso = (texto, tipo) => avisos.forEach((el) => {
      el.textContent = texto;
      el.className = "autosave" + (tipo ? " " + tipo : "");
    });
    const salvar = async () => {
      const atual = serializar();
      if (salvando || atual === ultimo) return;
      salvando = true;
      aviso("Salvando…");
      try {
        const resp = await fetch(url, { method: "POST", body: new FormData(form), credentials: "same-origin" });
        const r = await resp.json();
        if (r.ok) {
          ultimo = atual;
          aviso("✓ Salvo às " + r.hora, "ok");
        } else {
          aviso("Não foi salvo: " + Object.values(r.erros)[0], "erro");
        }
      } catch (_) {
        aviso("Sem conexão: o salvamento será tentado de novo em instantes.", "erro");
      } finally {
        salvando = false;
      }
    };
    horaAuto?.addEventListener("input", () => { editadaAMao = true; });
    setInterval(() => {
      if (horaAuto && !editadaAMao) horaAuto.value = horaAgora();
      salvar();
    }, intervalo);
    form.addEventListener("change", salvar);
    // Ao sair (fechar a aba, trocar de app no celular), envia o que faltou salvar
    const enviarAoSair = () => {
      if (serializar() !== ultimo && navigator.sendBeacon) {
        navigator.sendBeacon(url, new FormData(form));
        ultimo = serializar();
      }
    };
    window.addEventListener("pagehide", enviarAoSair);
    document.addEventListener("visibilitychange", () => { if (document.visibilityState === "hidden") enviarAoSair(); });
  });

  // Campo que envia o próprio formulário ao mudar (ano da tela de gerenciar, arquivo da planilha)
  document.querySelectorAll("[data-enviar-ao-mudar]").forEach((el) => {
    el.addEventListener("change", () => { if (el.type !== "file" || el.files.length) el.form.submit(); });
  });

  // Gerenciar sessões (tela de leitura): caixa das sugestões, contador "cria · atualiza"
  // e aviso ao sair com a prévia da planilha ainda não gravada
  const ger = document.querySelector("form[data-gerenciar]");
  if (ger) {
    const resumo = ger.querySelector("[data-resumo]");
    const gravar = ger.querySelector("[data-gravar]");
    const previa = !!ger.querySelector(".da-planilha");
    let enviando = false;
    const contar = () => {
      let cria = 0;
      let atualiza = 0;
      ger.querySelectorAll("[data-linha]").forEach((linha) => {
        const origem = linha.dataset.origem;
        const incluir = linha.querySelector("[data-incluir]");
        if (incluir) linha.classList.toggle("desmarcada", !incluir.checked);
        if (origem === "nova" || (origem === "sugestao" && incluir.checked)) cria++;
        else if (origem === "cadastrada" && linha.classList.contains("da-planilha")) atualiza++;
      });
      ger.querySelectorAll("[data-evento-planilha]").forEach((ev) => {
        if (ev.dataset.eventoPlanilha === "novo") cria++;
        else atualiza++;
      });
      const partes = [];
      if (cria) partes.push(`cria ${cria}`);
      if (atualiza) partes.push(`atualiza ${atualiza}`);
      resumo.textContent = partes.length ? partes.join(" · ") : "Nenhuma sessão marcada.";
      gravar.disabled = !partes.length;
      return cria + atualiza;
    };
    ger.addEventListener("change", contar);
    ger.querySelectorAll("[data-marcar-todas]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const marcar = btn.dataset.marcarTodas === "1";
        ger.querySelectorAll("[data-incluir]").forEach((chk) => { chk.checked = marcar; });
        contar();
      });
    });
    ger.addEventListener("submit", () => { enviando = true; });
    window.addEventListener("beforeunload", (ev) => {
      if (previa && !enviando && contar() > 0) { ev.preventDefault(); ev.returnValue = ""; }
    });
    contar();
  }

  // Contrato do Parque: mostra os campos de pessoa física ou de pessoa jurídica
  const tiposPessoa = document.querySelectorAll("[data-tipo-pessoa]");
  if (tiposPessoa.length) {
    const aplicarTipo = () => {
      const tipo = document.querySelector("[data-tipo-pessoa]:checked")?.value || "PF";
      document.querySelectorAll("[data-so-tipo]").forEach((el) => el.classList.toggle("oculto", el.dataset.soTipo !== tipo));
    };
    tiposPessoa.forEach((r) => r.addEventListener("change", aplicarTipo));
    aplicarTipo();
  }

  // Mantém o mês selecionado visível na barra de meses
  document.querySelector("[data-rolar]")?.scrollIntoView({ inline: "center", block: "nearest" });

  // Agenda: a legenda também é filtro. Vários itens podem ficar marcados; nenhum = mostra tudo.
  // O filtro continua ao trocar de mês/ano (guardado só nesta aba do navegador).
  const legenda = document.querySelector("[data-filtro-agenda]");
  if (legenda) {
    const CHAVE = "agenda-filtro";
    const botoes = [...legenda.querySelectorAll("[data-filtro]")];
    const itens = [...document.querySelectorAll(".lista.agenda > li[data-cat]")];
    const vazio = document.querySelector("[data-filtro-vazio]");
    const nomes = Object.fromEntries(botoes.map((b) => [b.dataset.filtro, b.textContent.trim()]));
    let marcados = new Set();
    try { marcados = new Set(JSON.parse(sessionStorage.getItem(CHAVE) || "[]").filter((c) => c in nomes)); } catch (_) {}

    const aplicar = () => {
      botoes.forEach((b) => b.setAttribute("aria-pressed", marcados.has(b.dataset.filtro) ? "true" : "false"));
      legenda.classList.toggle("filtrando", marcados.size > 0);
      let visiveis = 0;
      itens.forEach((li) => {
        const mostra = !marcados.size || marcados.has(li.dataset.cat);
        li.hidden = !mostra;
        if (mostra) visiveis++;
      });
      if (vazio) {
        const lista = [...marcados].map((c) => nomes[c]);
        const texto = lista.length > 1 ? lista.slice(0, -1).join(", ") + " ou " + lista.at(-1) : lista[0];
        vazio.querySelector("[data-filtro-texto]").textContent =
          `Nenhum compromisso de ${texto} em ${legenda.dataset.mesNome}.`;
        vazio.classList.toggle("oculto", !(itens.length && marcados.size && !visiveis));
      }
      try { sessionStorage.setItem(CHAVE, JSON.stringify([...marcados])); } catch (_) {}
    };
    botoes.forEach((b) => b.addEventListener("click", () => {
      const cat = b.dataset.filtro;
      if (marcados.has(cat)) marcados.delete(cat); else marcados.add(cat);
      aplicar();
    }));
    aplicar();
  }

  // Copiar texto (ex.: chave PIX) com um toque
  const copiarTexto = async (texto) => {
    if (navigator.clipboard && window.isSecureContext) {
      try {
        await Promise.race([navigator.clipboard.writeText(texto),
                            new Promise((_, falha) => setTimeout(falha, 1500))]);
        return true;
      } catch (_) { /* tenta o método clássico */ }
    }
    const campo = document.createElement("textarea");
    campo.value = texto;
    campo.setAttribute("readonly", "");
    campo.style.cssText = "position:fixed;top:0;left:0;opacity:0";
    document.body.appendChild(campo);
    campo.select();
    campo.setSelectionRange(0, texto.length);
    let ok = false;
    try { ok = document.execCommand("copy"); } catch (_) {}
    campo.remove();
    return ok;
  };
  document.querySelectorAll("[data-copiar]").forEach((el) => {
    const aviso = el.parentElement.querySelector("[data-copiar-aviso]");
    const textoAviso = aviso ? aviso.textContent : "";
    el.addEventListener("click", async () => {
      const ok = await copiarTexto(el.dataset.copiar);
      el.classList.toggle("copiado", ok);
      if (aviso) {
        aviso.textContent = ok ? "✓ Chave copiada! Cole no aplicativo do seu banco."
                               : "Não foi possível copiar sozinho: toque e segure a chave para copiar.";
        setTimeout(() => { aviso.textContent = textoAviso; el.classList.remove("copiado"); }, 3000);
      }
    });
  });

  // Relatórios: imprimir / salvar em PDF
  document.querySelectorAll("[data-imprimir]").forEach((btn) => {
    btn.addEventListener("click", () => window.print());
  });

  // Valores em reais: aceita só dígitos, vírgula e ponto; formata com 2 casas ao sair do campo
  document.querySelectorAll("[data-moeda]").forEach((el) => {
    el.addEventListener("input", () => { el.value = el.value.replace(/[^\d.,]/g, ""); });
    el.addEventListener("blur", () => {
      let v = el.value.trim();
      if (!v) return;
      if (v.includes(",")) v = v.replace(/\./g, "").replace(",", ".");
      else if (/^\d{1,3}(\.\d{3})+$/.test(v)) v = v.replace(/\./g, "");
      const n = Number(v);
      if (Number.isFinite(n) && n > 0) {
        el.value = n.toLocaleString("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
      }
    });
  });

  // PWA: permite "Adicionar à tela inicial"
  if ("serviceWorker" in navigator) {
    window.addEventListener("load", () => navigator.serviceWorker.register("/sw.js").catch(() => {}));
  }
})();
