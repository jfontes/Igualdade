/**
 * SISTEMA DE CADASTRO - IGUALDADE ACREANA
 * Versão: Bordô Consolidado (#560710)
 */

function mascaraCPF(i) {
    let v = i.value.replace(/\D/g, "");
    if (v.length <= 11) {
        v = v.replace(/(\d{3})(\d)/, "$1.$2");
        v = v.replace(/(\d{3})(\d)/, "$1.$2");
        v = v.replace(/(\d{3})(\d{1,2})$/, "$1-$2");
    }
    i.value = v;
}

function mascaraCEP(i) {
    let v = i.value.replace(/\D/g, "");
    if (v.length > 5) {
        v = v.substring(0, 5) + "-" + v.substring(5, 8);
    }
    i.value = v;
}

async function buscarCEP(valor) {
    const cep = valor.replace(/\D/g, "");
    const loader = document.getElementById('loader-cep');
    if (cep.length === 8) {
        loader.classList.remove('hidden');
        try {
            const resposta = await fetch(`https://viacep.com.br/ws/${cep}/json/`);
            const dados = await resposta.json();
            if (!dados.erro) {
                document.getElementById('logradouro').value = dados.logradouro.toUpperCase();
                document.getElementById('bairro').value = dados.bairro.toUpperCase();
                document.getElementById('cidade').value = dados.localidade.toUpperCase();
                document.getElementById('estado').value = dados.uf.toUpperCase();
                document.getElementById('logradouro').readOnly = false;
                document.getElementById('numero').focus();
            } else {
                alert("CEP NÃO ENCONTRADO.");
            }
        } catch (erro) {
            console.error("Erro na busca do CEP:", erro);
        } finally {
            loader.classList.add('hidden');
        }
    }
}

async function buscarCIM() {
    const cimInput = document.getElementById('cim');
    const cim = cimInput.value.replace(/\D/g, "");
    if (!cim) {
        alert("POR FAVOR, DIGITE UM CIM PARA BUSCAR.");
        cimInput.focus();
        return;
    }

    const btnBuscar = document.getElementById('btn-buscar-cim');
    const svgBusca = btnBuscar.innerHTML;
    btnBuscar.innerHTML = `<svg class="animate-spin h-5 w-5 text-[#560710]" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg>`;
    btnBuscar.disabled = true;

    try {
        const urlAPI = `https://igualdade.onrender.com/obreiros/${cim}`;
        const resposta = await fetch(urlAPI, {
            method: 'GET',
            cache: 'no-store'
        });

        if (resposta.ok) {
            const dados = await resposta.json();
            
            document.getElementById('nome').value = dados.nome || "";
            document.getElementById('cpf').value = dados.cpf || "";
            if(dados.cpf) mascaraCPF(document.getElementById('cpf'));
            document.getElementById('data_nascimento').value = dados.data_nascimento || "";
            
            document.getElementById('cep').value = dados.cep || "";
            if(dados.cep) mascaraCEP(document.getElementById('cep'));
            document.getElementById('logradouro').value = dados.logradouro || "";
            document.getElementById('numero').value = dados.numero || "";
            document.getElementById('bairro').value = dados.bairro || "";
            document.getElementById('cidade').value = dados.cidade || "";
            document.getElementById('estado').value = dados.estado || "";
            
            document.getElementById('data_iniciacao').value = dados.data_iniciacao || "";
            document.getElementById('data_elevacao').value = dados.data_elevacao || "";
            document.getElementById('data_exaltacao').value = dados.data_exaltacao || "";
            document.getElementById('data_filiacao').value = dados.data_filiacao || "";
            document.getElementById('data_afastamento').value = dados.data_afastamento || "";
            
            const containerFamiliares = document.getElementById('lista-familiares');
            containerFamiliares.innerHTML = ""; 
            if (dados.familiares && dados.familiares.length > 0) {
                dados.familiares.forEach(fam => adicionarCampoFamiliar(fam));
            }
        } else if (resposta.status === 404) {
            // Verifica se o 404 é da nossa API (Obreiro não encontrado) ou do FastAPI (Rota não encontrada)
            const erroInfo = await resposta.json().catch(() => ({}));
            if (erroInfo.detail === "Not Found") {
                alert("SISTEMA DESATUALIZADO: O servidor ainda está aplicando a atualização (Deploy no Render). Aguarde 1 a 2 minutinhos e tente de novo!");
            } else {
                alert("CIM NÃO ENCONTRADO. Pode prosseguir com o novo cadastro.");
            }
        } else {
            alert("ERRO AO BUSCAR DADOS NO SERVIDOR.");
        }
    } catch (erro) {
        console.error("Erro na busca:", erro);
        alert("FALHA DE CONEXÃO AO BUSCAR CIM.");
    } finally {
        btnBuscar.innerHTML = svgBusca;
        btnBuscar.disabled = false;
    }
}

function adicionarCampoFamiliar(dadosFamiliar = null) {
    const container = document.getElementById('lista-familiares');
    const div = document.createElement('div');
    // Cores: Fundo bordô claríssimo (#fdf2f2) e borda bordô suave (#ecdada)
    div.className = "p-4 bg-[#fdf2f2] rounded-xl border border-[#ecdada] relative mb-4 shadow-sm animate-fade-in";
    
    div.innerHTML = `
        <select style="color: #560710;" class="tipo-familiar w-full p-3 mb-3 rounded-lg border-[#ecdada] font-bold bg-white outline-none focus:ring-2 focus:ring-[#560710]">
            <option value="Cunhada">CUNHADA</option>
            <option value="Sobrinho">SOBRINHO</option>
            <option value="Sobrinha">SOBRINHA</option>
        </select>
        <input type="text" class="nome-familiar w-full p-3 mb-3 rounded-lg border-[#ecdada] uppercase outline-none focus:ring-2 focus:ring-[#560710]" placeholder="NOME DO FAMILIAR">
        <div class="flex flex-col">
            <label style="color: #560710;" class="text-[10px] font-bold ml-1 mb-1 opacity-70">DATA DE NASCIMENTO</label>
            <input type="date" style="color: #560710;" class="data-familiar w-full p-3 rounded-lg border-[#ecdada] bg-white outline-none">
        </div>
        <button type="button" onclick="this.parentElement.remove()" class="absolute -top-2 -right-2 bg-[#560710] text-white rounded-full w-8 h-8 flex items-center justify-center font-bold shadow-md border-2 border-white">×</button>
    `;
    container.appendChild(div);
    
    if (dadosFamiliar) {
        div.querySelector('.tipo-familiar').value = dadosFamiliar.tipo_parentesco || "Cunhada";
        div.querySelector('.nome-familiar').value = dadosFamiliar.nome || "";
        if (dadosFamiliar.data_nascimento) {
            div.querySelector('.data-familiar').value = dadosFamiliar.data_nascimento;
        }
    }
}

function marcarErro(id) {
    const campo = document.getElementById(id);
    campo.classList.add('border-red-500', 'bg-red-50', 'ring-1', 'ring-red-200');
    campo.placeholder = "CAMPO OBRIGATÓRIO";
    campo.onfocus = () => {
        campo.classList.remove('border-red-500', 'bg-red-50', 'ring-1', 'ring-red-200');
    };
}

async function enviarDados() {
    const btn = document.getElementById('btnSalvar');
    const obrigatorios = ['nome', 'cim', 'cpf', 'data_nascimento', 'cep', 'logradouro', 'numero', 'bairro', 'cidade', 'estado'];
    let formValido = true;

    obrigatorios.forEach(id => {
        const campo = document.getElementById(id);
        if (!campo.value.trim()) {
            marcarErro(id);
            formValido = false;
        }
    });

    if (!formValido) {
        alert("POR FAVOR, PREENCHA TODOS OS CAMPOS EM DESTAQUE.");
        window.scrollTo(0, 0);
        return;
    }

    btn.disabled = true;
    const textoOriginal = btn.innerText;
    btn.innerText = "PROCESSANDO...";

    const dados = {
        nome: document.getElementById('nome').value.toUpperCase(),
        cim: document.getElementById('cim').value.replace(/\D/g, ""),
        cpf: document.getElementById('cpf').value,
        data_nascimento: document.getElementById('data_nascimento')?.value || null,
        data_iniciacao: document.getElementById('data_iniciacao')?.value || null,
        data_elevacao: document.getElementById('data_elevacao')?.value || null,
        data_exaltacao: document.getElementById('data_exaltacao')?.value || null,
        data_filiacao: document.getElementById('data_filiacao')?.value || null,
        data_afastamento: document.getElementById('data_afastamento')?.value || null,
        cep: document.getElementById('cep').value,
        logradouro: document.getElementById('logradouro').value.toUpperCase(),
        numero: document.getElementById('numero').value.replace(/\D/g, ""),
        bairro: document.getElementById('bairro').value.toUpperCase(),
        cidade: document.getElementById('cidade').value.toUpperCase(),
        estado: document.getElementById('estado').value.toUpperCase(),
        familiares: []
    };

    const blocosFamiliares = document.querySelectorAll('#lista-familiares > div');
    let familiarSemNome = false;

    blocosFamiliares.forEach(bloco => {
        const inputNome = bloco.querySelector('.nome-familiar');
        if (!inputNome.value.trim()) {
            inputNome.classList.add('border-red-500', 'bg-red-50');
            familiarSemNome = true;
        } else {
            dados.familiares.push({
                tipo_parentesco: bloco.querySelector('.tipo-familiar').value,
                nome: inputNome.value.toUpperCase(),
                data_nascimento: bloco.querySelector('.data-familiar').value || null
            });
        }
    });

    if (familiarSemNome) {
        alert("PREENCHA O NOME DO FAMILIAR ADICIONADO OU REMOVA O BLOCO.");
        btn.disabled = false;
        btn.innerText = textoOriginal;
        return;
    }

    // DEBUG: Mostra no console do navegador o objeto que será enviado para a API
    console.log("DEBUG - Dados montados para envio:", JSON.stringify(dados, null, 2));

    try {
        const urlAPI = 'https://igualdade.onrender.com/cadastrar'; // Sem a barra extra no final se não houver no Python
        const resposta = await fetch(urlAPI, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(dados)
        });

        if (resposta.ok) {
            alert("CADASTRO REALIZADO COM SUCESSO!");
            location.reload();
        } else {
            // DEBUG: Extrai o erro detalhado enviado pelo FastAPI (geralmente no campo 'detail')
            const erroDetalhado = await resposta.json();
            console.error("DEBUG - Erro retornado pelo servidor HTTP " + resposta.status + ":", erroDetalhado);
            alert(`ERRO NO SERVIDOR: ${erroDetalhado.detail || "Verifique o console para mais detalhes."}`);
        }
    } catch (e) {
        // DEBUG: Captura falhas de rede (ex: servidor offline, erro de CORS)
        console.error("DEBUG - Falha na requisição (Network/CORS):", e);
        alert("FALHA DE CONEXÃO. O servidor pode estar iniciando ou está offline.");
    } finally {
        btn.disabled = false;
        btn.innerText = textoOriginal;
    }
}
