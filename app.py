import streamlit as st
import pandas as pd
import re
import unicodedata
from datetime import datetime
import os

# --- Configuração da Página ---
st.set_page_config(page_title="Análise de Atualização de Projetos", page_icon="⚙️", layout="wide")

# --- Funções Utilitárias ---

def padronizar_nome(texto):
    """Normaliza o nome da cidade para busca no CSV."""
    if not isinstance(texto, str): return texto
    texto = re.sub(r'\s*\([^)]*\)', '', texto)
    texto_normalizado = unicodedata.normalize('NFKD', texto).encode('ascii', 'ignore').decode('utf-8').strip().lower()
    return re.sub(r'\s+', '_', texto_normalizado)

def parse_potencia_numerica(texto_potencia):
    """Extrai um número de uma string, mesmo com 'kWp' ou vírgulas."""
    if not isinstance(texto_potencia, str): return None
    match = re.search(r'[\d,.]+', texto_potencia)
    if match:
        try:
            return float(match.group(0).replace(',', '.'))
        except (ValueError, TypeError):
            return None
    return None

# --- FUNÇÃO DE ANÁLISE COM SAÍDA DETALHADA E DIRETA ---
def gerar_instrucao_tecnica(cidade, tipo_ligacao, carga_instalada, potencia_kit_kwp, df_tensao, df_dados_tecnicos, mapa_ligacao):
    """
    Analisa os dados e retorna uma instrução detalhada e direta.
    """
    if not all([cidade, tipo_ligacao, potencia_kit_kwp]):
        return "ERRO: Preencha os campos essenciais para análise (Cidade, Fase, Carga e Potência do Kit ATUAL)."

    cidade_norm = padronizar_nome(cidade)
    tensao_info = df_tensao.loc[df_tensao["municipio"] == cidade_norm, "tensao"]
    if tensao_info.empty: return f"ERRO: Tensão para a cidade '{cidade}' não encontrada."
    tensao = tensao_info.values[0]

    categorias_permitidas = mapa_ligacao.get(tipo_ligacao, [])
    df_faixa_encontrada = df_dados_tecnicos[
        (df_dados_tecnicos["tensao"] == tensao) &
        (df_dados_tecnicos["categoria"].isin(categorias_permitidas)) &
        (carga_instalada >= df_dados_tecnicos["carga_min_kw"]) &
        (carga_instalada <= df_dados_tecnicos["carga_max_kw"])
    ]

    if df_faixa_encontrada.empty: return f"ERRO: Nenhuma faixa encontrada para os dados atuais (Carga: {carga_instalada}kW, Ligação: {tipo_ligacao})."

    resultado_atual = df_faixa_encontrada.iloc[0]
    limite_atual = resultado_atual["limite_numerico_busca"]
    faixa_atual = resultado_atual["categoria"]
    limite_atual_str = str(resultado_atual.get('potencia_maxima_geracao_str', 'N/A'))

    if pd.isna(limite_atual):
        return f"APROVADO: O projeto pode ser atualizado. A faixa atual ({faixa_atual}) não possui um limite de potência definido."

    if potencia_kit_kwp <= limite_atual:
        return f"APROVADO: O projeto pode ser atualizado. O cliente se mantém na faixa atual ({faixa_atual}), que possui um limite de {limite_atual_str}."

    # Se chegou aqui, o kit excede o limite.
    reprovado_msg = f"**REPROVADO PARA ATUALIZAÇÃO:** O kit de **{potencia_kit_kwp:.2f} kWp** excede o limite de **{limite_atual_str}** para a categoria atual (`{faixa_atual}`)."

    tipos_de_busca = ["Monofásico", "Bifásico", "Trifásico"]
    try:
        indice_inicio_busca = tipos_de_busca.index(tipo_ligacao)
    except ValueError:
        return f"ERRO: Tipo de ligação '{tipo_ligacao}' inválido."

    for tipo_busca in tipos_de_busca[indice_inicio_busca:]:
        categorias_busca = mapa_ligacao.get(tipo_busca, [])
        df_solucao = df_dados_tecnicos[
            (df_dados_tecnicos["tensao"] == tensao) &
            (df_dados_tecnicos["categoria"].isin(categorias_busca)) &
            (df_dados_tecnicos["limite_numerico_busca"] >= potencia_kit_kwp)
        ].sort_values(by="carga_min_kw")

        if not df_solucao.empty:
            solucao = df_solucao.iloc[0]
            nova_faixa = solucao['categoria']
            nova_carga_min_kw = solucao['carga_min_kw']
            nova_carga_max_kw = solucao['carga_max_kw']
            novo_limite_str = solucao.get('potencia_maxima_geracao_str', 'N/A')
            
            solucao_partes = []
            titulo_solucao = "💡 **Solução Sugerida:**"
            if tipo_busca != tipo_ligacao:
                titulo_solucao = f"💡 **Solução Sugerida (com upgrade de ligação):**"
            solucao_partes.append(titulo_solucao)

            if tipo_busca != tipo_ligacao:
                solucao_partes.append(f"É necessário solicitar à concessionária a **alteração para Ligação {tipo_busca}**.")
            
            solucao_partes.append(f"**Carga Instalada Necessária:** Entre {nova_carga_min_kw:.2f} kW e {nova_carga_max_kw:.2f} kW.")
            solucao_partes.append(f"Com a nova categoria (`{nova_faixa}`), o limite de potência do kit será de **{novo_limite_str}**.")
            
            solucao_msg = "\n".join(solucao_partes)
            
            return f"{reprovado_msg}__SEPARADOR__{solucao_msg}"
            
    return f"{reprovado_msg}__SEPARADOR__NÃO FOI ENCONTRADA SOLUÇÃO para um kit de {potencia_kit_kwp} kWp com a tensão de {tensao}."

# --- Carregamento de Dados ---
@st.cache_data
def carregar_dados_tecnicos():
    try:
        df_tensao = pd.read_csv("municipios_tensao.csv", sep=r'\s*,\s*', engine='python')
        df_disjuntores = pd.read_csv("tabela_disjuntores.csv", sep=r'\s*,\s*', engine='python')
        df_potencia_max = pd.read_csv("tabela_potencia_maxima.csv", sep=r'\s*,\s*', engine='python')
    except FileNotFoundError as e:
        st.error(f"Erro: O arquivo `{e.filename}` não foi encontrado. Certifique-se de que os 3 arquivos .csv estão na mesma pasta do aplicativo.")
        return None, None, None

    for df in [df_tensao, df_disjuntores, df_potencia_max]:
        df.columns = [padronizar_nome(col) for col in df.columns]
        if 'tensao' in df.columns:
            df['tensao'] = df['tensao'].astype(str).str.strip().str.replace('V$', '', regex=True)

    if 'municipio' in df_tensao.columns:
        df_tensao['municipio'] = df_tensao['municipio'].str.strip().apply(padronizar_nome)
    else:
        st.error("Erro: Coluna 'municipio' não encontrada em `municipios_tensao.csv`.")
        return None, None, None

    def parse_carga_range(range_str):
        if not isinstance(range_str, str) or range_str.strip() == '-': return 0.0, 0.0
        try:
            range_str = range_str.replace(',', '.').strip()
            parts = [p.strip() for p in range_str.split('-')]
            if len(parts) == 2: return float(parts[0]), float(parts[1])
            elif len(parts) == 1 and parts[0]: val = float(parts[0]); return val, val
            else: return 0.0, 0.0
        except: return 0.0, 0.0

    if 'carga_instalada' in df_disjuntores.columns:
        cargas = df_disjuntores['carga_instalada'].apply(parse_carga_range)
        df_disjuntores[['carga_min_kw', 'carga_max_kw']] = pd.DataFrame(cargas.tolist(), index=df_disjuntores.index)
    else:
        st.error("Erro: Coluna 'carga_instalada' não encontrada em `tabela_disjuntores.csv`.")
        return None, None, None

    df_dados_tecnicos = pd.merge(df_disjuntores, df_potencia_max, on=['tensao', 'categoria'], how='left')
    coluna_pot = [col for col in df_dados_tecnicos.columns if 'potencia_maxima' in col]
    if coluna_pot:
        df_dados_tecnicos.rename(columns={coluna_pot[0]: 'potencia_maxima_geracao_str'}, inplace=True)
        df_dados_tecnicos['limite_numerico_busca'] = df_dados_tecnicos['potencia_maxima_geracao_str'].apply(parse_potencia_numerica)
    else:
        st.error("Erro: Coluna de potência máxima não encontrada em `tabela_potencia_maxima.csv`.")
        return None, None, None

    mapa_ligacao = {"Monofásico": ["M0", "M1", "M2", "M3"], "Bifásico": ["B0", "B1", "B2"], "Trifásico": [f"T{i}" for i in range(13)]}
    return df_tensao, df_dados_tecnicos, mapa_ligacao

# --- Função para salvar dados no CSV ---
def salvar_dados_csv(dados, nome_arquivo="atualizacoes_projetos.csv"):
    if os.path.exists(nome_arquivo):
        df_existente = pd.read_csv(nome_arquivo)
        df_atualizado = pd.concat([df_existente, dados], ignore_index=True)
    else:
        df_atualizado = dados
    df_atualizado.to_csv(nome_arquivo, index=False)
    st.success("✅ Registro salvo com sucesso no histórico!")


# --- Interface Principal do App ---
st.title("⚙️ Analisador e Registrador de Atualizações")
st.markdown("Preencha todos os campos para registro e use a análise para verificar a conformidade do projeto.")

df_tensao, df_dados_tecnicos, mapa_ligacao = carregar_dados_tecnicos()

if df_dados_tecnicos is not None:
    with st.form("form_registro_e_analise"):
        st.header("1. Dados para Registro")
        
        cliente = st.text_input("CLIENTE")
        data_envio = st.date_input("Data do Envio", value=datetime.today())
        
        status = st.selectbox("Status do Registro", ["", "Atualizado", "Solicitado Mudança"], help="Selecione o status deste registro.")
        
        cidade = st.text_input("Cidade")
        fase = st.selectbox("Fase da ligação", ["Monofásico", "Bifásico", "Trifásico"])
        carga_instalada_kw = st.number_input("Carga Instalada (kW)", min_value=0.0, step=0.1, format="%.2f")

        st.divider()
        col1, col2, col3 = st.columns(3)
        with col1:
            st.subheader("Kit Instalado")
            kit_inst_pot = st.text_input("POTÊNCIA", key="inst_pot")
            kit_inst_placa = st.text_input("PLACA", key="inst_placa")
            kit_inst_inversor = st.text_input("INVERSOR", key="inst_inv")
        with col2:
            st.subheader("Kit Enviado")
            kit_env_pot = st.text_input("POTÊNCIA", key="env_pot")
            kit_env_placa = st.text_input("PLACA", key="env_placa")
            kit_env_inversor = st.text_input("INVERSOR", key="env_inv")
        with col3:
            st.subheader("Kit ATUAL Instalado")
            kit_atual_pot = st.text_input("POTÊNCIA", key="atual_pot")
            kit_atual_placa = st.text_input("PLACA", key="atual_placa")
            kit_atual_inversor = st.text_input("INVERSOR", key="atual_inv")
        
        st.divider()
        comentario_notion = st.text_area("Comentário do Notion")
        
        st.header("2. Análise de Conformidade")
        st.info("A análise usará os campos: Cidade, Fase, Carga Instalada e a Potência do Kit ATUAL.")
        
        analisar_btn = st.form_submit_button("Analisar Conformidade do Kit ATUAL")

        if 'instrucao' not in st.session_state:
            st.session_state.instrucao = ""

        if analisar_btn:
            potencia_para_analise = parse_potencia_numerica(kit_atual_pot)
            with st.spinner("Analisando..."):
                st.session_state.instrucao = gerar_instrucao_tecnica(
                    cidade, fase, carga_instalada_kw, potencia_para_analise,
                    df_tensao, df_dados_tecnicos, mapa_ligacao
                )
        
        if st.session_state.instrucao:
            instrucao = st.session_state.instrucao
            if "ERRO" in instrucao:
                st.error(instrucao)
            elif "__SEPARADOR__" in instrucao:
                partes = instrucao.split("__SEPARADOR__")
                st.error(partes[0])
                st.info(partes[1])
            else:
                st.success(instrucao)

        st.header("3. Salvar Registro")
        salvar_btn = st.form_submit_button("✅ Salvar Registro Completo no Histórico", use_container_width=True)
        
        if salvar_btn:
            if not status:
                st.error("ERRO AO SALVAR: Por favor, selecione um 'Status do Registro' antes de salvar.")
            else:
                instrucao_para_salvar = st.session_state.instrucao.replace("__SEPARADOR__", "\n\n")
                nova_linha = pd.DataFrame([{
                    "Cliente": cliente, "Data de Envio": data_envio, "Status": status, "Cidade": cidade, "Fase": fase, "Carga Instalada (kW)": carga_instalada_kw,
                    "Kit Instalado - Potência": kit_inst_pot, "Kit Instalado - Placa": kit_inst_placa, "Kit Instalado - Inversor": kit_inst_inversor,
                    "Kit Enviado - Potência": kit_env_pot, "Kit Enviado - Placa": kit_env_placa, "Kit Enviado - Inversor": kit_env_inversor,
                    "Kit ATUAL - Potência": kit_atual_pot, "Kit ATUAL - Placa": kit_atual_placa, "Kit ATUAL - Inversor": kit_atual_inversor,
                    "Comentário Notion": comentario_notion, "Instrução da Análise": instrucao_para_salvar
                }])
                salvar_dados_csv(nova_linha)
                st.session_state.instrucao = ""

# --- Visualização do Histórico ---
if os.path.exists("atualizacoes_projetos.csv"):
    st.divider()
    st.header("📋 Histórico de Atualizações")
    df_historico = pd.read_csv("atualizacoes_projetos.csv")

    if 'Status' not in df_historico.columns:
        df_historico['Status'] = 'N/A'
    
    status_options = ["Todos"] + list(df_historico["Status"].unique())
    status_filter = st.selectbox(
        "Filtrar por Status:",
        options=status_options
    )
    
    if status_filter == "Todos":
        df_filtrado = df_historico
    else:
        df_filtrado = df_historico[df_historico["Status"] == status_filter]

    # --- ALTERAÇÃO: Nova visualização com st.expander ---
    for index, row in df_filtrado.iterrows():
        # Assegura que os valores sejam strings para evitar erros
        cliente_nome = str(row.get("Cliente", "N/A"))
        status_valor = str(row.get("Status", "N/A"))
        
        # Cria o título do expander
        expander_title = f"{cliente_nome}  |  Status: {status_valor}"
        
        with st.expander(expander_title):
            st.markdown(f"**Data de Envio:** {row.get('Data de Envio', 'N/A')}")
            st.markdown(f"**Cidade:** {row.get('Cidade', 'N/A')}")
            st.markdown(f"**Fase:** {row.get('Fase', 'N/A')}")
            st.markdown(f"**Carga Instalada (kW):** {row.get('Carga Instalada (kW)', 'N/A')}")
            
            st.divider()
            
            c1, c2, c3 = st.columns(3)
            with c1:
                st.markdown("**Kit Instalado**")
                st.text(f"Potência: {row.get('Kit Instalado - Potência', 'N/A')}")
                st.text(f"Placa: {row.get('Kit Instalado - Placa', 'N/A')}")
                st.text(f"Inversor: {row.get('Kit Instalado - Inversor', 'N/A')}")
            with c2:
                st.markdown("**Kit Enviado**")
                st.text(f"Potência: {row.get('Kit Enviado - Potência', 'N/A')}")
                st.text(f"Placa: {row.get('Kit Enviado - Placa', 'N/A')}")
                st.text(f"Inversor: {row.get('Kit Enviado - Inversor', 'N/A')}")
            with c3:
                st.markdown("**Kit ATUAL Instalado**")
                st.text(f"Potência: {row.get('Kit ATUAL - Potência', 'N/A')}")
                st.text(f"Placa: {row.get('Kit ATUAL - Placa', 'N/A')}")
                st.text(f"Inversor: {row.get('Kit ATUAL - Inversor', 'N/A')}")
            
            st.divider()
            
            st.markdown("**Comentário do Notion:**")
            st.text(row.get('Comentário Notion', ''))
            
            st.markdown("**Instrução da Análise:**")
            instrucao_texto = str(row.get('Instrução da Análise', ''))
            
            # Formata a exibição da instrução
            if "ERRO" in instrucao_texto:
                st.error(instrucao_texto)
            elif "REPROVADO" in instrucao_texto:
                partes = instrucao_texto.split("\n\n")
                st.warning(partes[0])
                if len(partes) > 1:
                    st.info("\n\n".join(partes[1:]))
            else:
                st.success(instrucao_texto)


st.caption("Desenvolvido por Vitória de Sales Sena ⚡")
