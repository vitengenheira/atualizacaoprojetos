import streamlit as st
import pandas as pd
import re
import unicodedata
from datetime import datetime
import os

# --- Configuração da Página ---
st.set_page_config(page_title="Gestor de Atualizações de Projetos", page_icon="⚙️", layout="wide")

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

# --- FUNÇÃO DE ANÁLISE ---
def gerar_instrucao_tecnica(cidade, tipo_ligacao, carga_instalada, potencia_para_analise, df_tensao, df_dados_tecnicos, mapa_ligacao):
    """
    Analisa os dados e retorna uma tupla (instrução, status_sugerido).
    """
    if not all([cidade, tipo_ligacao, potencia_para_analise]):
        return ("ERRO: Preencha os campos essenciais para análise (Cidade, Fase, Carga e Potências do Kit ATUAL).", "Erro de Análise")

    cidade_norm = padronizar_nome(cidade)
    tensao_info = df_tensao.loc[df_tensao["municipio"] == cidade_norm, "tensao"]
    if tensao_info.empty: return (f"ERRO: Tensão para a cidade '{cidade}' não encontrada.", "Erro de Análise")
    tensao = tensao_info.values[0]

    categorias_permitidas = mapa_ligacao.get(tipo_ligacao, [])
    df_faixa_encontrada = df_dados_tecnicos[
        (df_dados_tecnicos["tensao"] == tensao) &
        (df_dados_tecnicos["categoria"].isin(categorias_permitidas)) &
        (carga_instalada >= df_dados_tecnicos["carga_min_kw"]) &
        (carga_instalada <= df_dados_tecnicos["carga_max_kw"])
    ]

    # --- ALTERAÇÃO: Mensagem de erro mais detalhada ---
    if df_faixa_encontrada.empty: return (f"ERRO: Nenhuma faixa encontrada para os dados atuais (Tensão: {tensao}, Carga: {carga_instalada}kW, Ligação: {tipo_ligacao}). Verifique se os arquivos CSV contêm uma categoria correspondente.", "Erro de Análise")

    resultado_atual = df_faixa_encontrada.iloc[0]
    limite_atual = resultado_atual["limite_numerico_busca"]
    faixa_atual = resultado_atual["categoria"]
    limite_atual_str = str(resultado_atual.get('potencia_maxima_geracao_str', 'N/A'))

    if pd.isna(limite_atual):
        return (f"APROVADO: O projeto pode ser atualizado. A faixa atual ({faixa_atual}) não possui um limite de potência definido.", "Enviar atualização")

    if potencia_para_analise <= limite_atual:
        return (f"APROVADO: O projeto pode ser atualizado. O cliente se mantém na faixa atual ({faixa_atual}), que possui um limite de {limite_atual_str}.", "Enviar atualização")

    reprovado_msg = f"**REPROVADO PARA ATUALIZAÇÃO:** A potência considerada (**{potencia_para_analise:.2f} kWp**) excede o limite de **{limite_atual_str}** para a categoria atual (`{faixa_atual}`)."

    tipos_de_busca = ["Monofásico", "Bifásico", "Trifásico"]
    try:
        indice_inicio_busca = tipos_de_busca.index(tipo_ligacao)
    except ValueError:
        return (f"ERRO: Tipo de ligação '{tipo_ligacao}' inválido.", "Erro de Análise")

    for tipo_busca in tipos_de_busca[indice_inicio_busca:]:
        categorias_busca = mapa_ligacao.get(tipo_busca, [])
        df_solucao = df_dados_tecnicos[
            (df_dados_tecnicos["tensao"] == tensao) &
            (df_dados_tecnicos["categoria"].isin(categorias_busca)) &
            (df_dados_tecnicos["limite_numerico_busca"] >= potencia_para_analise)
        ].sort_values(by="carga_min_kw")

        if not df_solucao.empty:
            solucao = df_solucao.iloc[0]
            nova_faixa, nova_carga_min_kw, nova_carga_max_kw, novo_limite_str = solucao['categoria'], solucao['carga_min_kw'], solucao['carga_max_kw'], solucao.get('potencia_maxima_geracao_str', 'N/A')
            
            solucao_partes = []
            if tipo_busca != tipo_ligacao:
                titulo_solucao = f"💡 **Solução Sugerida (com upgrade de ligação):**"
                solucao_partes.append(titulo_solucao)
                solucao_partes.append(f"1. **Solicitar à concessionária a alteração para Ligação {tipo_busca}**.")
                solucao_partes.append(f"2. **Adequar a Carga Instalada** para a faixa entre {nova_carga_min_kw:.2f} kW e {nova_carga_max_kw:.2f} kW (correspondente à nova categoria `{nova_faixa}`).")
            else: # Mesmo tipo de ligação, só muda a categoria
                titulo_solucao = "💡 **Solução Sugerida:**"
                solucao_partes.append(titulo_solucao)
                solucao_partes.append(f"1. **Mudar a categoria do projeto para `{nova_faixa}`**.")
                solucao_partes.append(f"2. **Adequar a Carga Instalada** para a nova faixa de {nova_carga_min_kw:.2f} kW a {nova_carga_max_kw:.2f} kW.")
            
            solucao_partes.append(f"Com esta alteração, o novo limite de potência do kit será de **{novo_limite_str}**.")
            
            solucao_msg = "\n".join(solucao_partes)
            return (f"{reprovado_msg}__SEPARADOR__{solucao_msg}", "Solicitar mudança")
            
    return (f"{reprovado_msg}__SEPARADOR__NÃO FOI ENCONTRADA SOLUÇÃO para um kit de {potencia_para_analise} kWp com a tensão de {tensao}.", "Erro de Análise")

# --- Carregamento de Dados ---
@st.cache_data
def carregar_dados_tecnicos():
    try:
        df_tensao = pd.read_csv("municipios_tensao.csv", sep=r'\s*,\s*', engine='python')
        df_disjuntores = pd.read_csv("tabela_disjuntores.csv", sep=r'\s*,\s*', engine='python')
        df_potencia_max = pd.read_csv("tabela_potencia_maxima.csv", sep=r'\s*,\s*', engine='python')
    except FileNotFoundError as e:
        st.error(f"Erro: O arquivo `{e.filename}` não foi encontrado.")
        return None, None, None

    # --- ALTERAÇÃO PRINCIPAL: Padroniza a tensão em todos os arquivos ---
    def standardize_voltage(v_str):
        if isinstance(v_str, str) and '/' in v_str:
            try:
                # Remove anything that isn't a digit or a slash.
                cleaned_str = re.sub(r'[^\d/]', '', v_str)
                # Split, convert to int, sort descending.
                parts = sorted([int(p) for p in cleaned_str.split('/')], reverse=True)
                return f"{parts[0]}/{parts[1]}"
            except (ValueError, IndexError):
                # If conversion fails, return the original cleaned string
                return v_str.strip().replace('V','').replace('v','')
        return v_str

    for df in [df_tensao, df_disjuntores, df_potencia_max]:
        df.columns = [padronizar_nome(col) for col in df.columns]
        if 'tensao' in df.columns:
            df['tensao'] = df['tensao'].astype(str).str.strip()
            df['tensao'] = df['tensao'].apply(standardize_voltage)

    if 'municipio' in df_tensao.columns:
        df_tensao['municipio'] = df_tensao['municipio'].str.strip().apply(padronizar_nome)
    else:
        st.error("Erro: Coluna 'municipio' não encontrada.")
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
        st.error("Erro: Coluna 'carga_instalada' não encontrada.")
        return None, None, None
    df_dados_tecnicos = pd.merge(df_disjuntores, df_potencia_max, on=['tensao', 'categoria'], how='left')
    coluna_pot = [col for col in df_dados_tecnicos.columns if 'potencia_maxima' in col]
    if coluna_pot:
        df_dados_tecnicos.rename(columns={coluna_pot[0]: 'potencia_maxima_geracao_str'}, inplace=True)
        df_dados_tecnicos['limite_numerico_busca'] = df_dados_tecnicos['potencia_maxima_geracao_str'].apply(parse_potencia_numerica)
    else:
        st.error("Erro: Coluna de potência máxima não encontrada.")
        return None, None, None
    mapa_ligacao = {"Monofásico": ["M0", "M1", "M2", "M3"], "Bifásico": ["B0", "B1", "B2"], "Trifásico": [f"T{i}" for i in range(13)]}
    return df_tensao, df_dados_tecnicos, mapa_ligacao

# --- Funções de Estado e Ações ---
def load_record_for_edit(df, index):
    record = df.loc[index].to_dict()
    st.session_state.edit_index = index
    for key, value in record.items():
        # Converte o nome da coluna para uma chave de estado válida
        state_key = f'edit_{re.sub(r"[^a-zA-Z0-9_]", "", key.replace(" ", "_"))}'
        st.session_state[state_key] = value

def clear_form():
    st.session_state.edit_index = None
    keys_to_clear = [k for k in st.session_state if k.startswith('edit_')]
    for k in keys_to_clear:
        del st.session_state[k]
    st.session_state.instrucao = ""
    st.session_state.status_sugerido = ""


# --- Interface Principal do App ---
st.title("⚙️ Gestor de Atualizações de Projetos")

# Inicialização do estado da sessão
if 'edit_index' not in st.session_state:
    st.session_state.edit_index = None
if 'instrucao' not in st.session_state:
    st.session_state.instrucao = ""
if 'status_sugerido' not in st.session_state:
    st.session_state.status_sugerido = ""


df_tensao, df_dados_tecnicos, mapa_ligacao = carregar_dados_tecnicos()

if df_dados_tecnicos is not None:
    # Determina o modo (edição ou novo)
    edit_mode = st.session_state.edit_index is not None
    form_title = "Editando Registro Existente" if edit_mode else "1. Adicionar Novo Registro"
    
    with st.expander(form_title, expanded=True):
        with st.form("form_registro"):
            # --- CAMPOS DE REGISTRO (agora preenchidos pelo estado da sessão) ---
            cliente = st.text_input("CLIENTE", value=st.session_state.get('edit_Cliente', ''))
            data_envio = st.date_input("Data do Envio", value=pd.to_datetime(st.session_state.get('edit_Data_de_Envio', datetime.today())))
            cidade = st.text_input("Cidade", value=st.session_state.get('edit_Cidade', ''))
            fase_options = ["Monofásico", "Bifásico", "Trifásico"]
            fase_index = fase_options.index(st.session_state.get('edit_Fase', 'Monofásico'))
            fase = st.selectbox("Fase da ligação", fase_options, index=fase_index)
            carga_instalada_kw = st.number_input("Carga Instalada (kW)", min_value=0.0, step=0.1, format="%.2f", value=st.session_state.get('edit_Carga_Instalada_kW', 0.0))

            st.divider()
            col1, col2, col3 = st.columns(3)
            with col1:
                st.subheader("Kit Instalado")
                kit_inst_pot = st.text_input("POTÊNCIA", key="inst_pot", value=st.session_state.get('edit_Kit_Instalado_-_Potência', ''))
                kit_inst_placa = st.text_input("PLACA", key="inst_placa", value=st.session_state.get('edit_Kit_Instalado_-_Placa', ''))
                kit_inst_inversor = st.text_input("INVERSOR", key="inst_inv", value=st.session_state.get('edit_Kit_Instalado_-_Inversor', ''))
            with col2:
                st.subheader("Kit Enviado")
                kit_env_pot = st.text_input("POTÊNCIA", key="env_pot", value=st.session_state.get('edit_Kit_Enviado_-_Potência', ''))
                kit_env_placa = st.text_input("PLACA", key="env_placa", value=st.session_state.get('edit_Kit_Enviado_-_Placa', ''))
                kit_env_inversor = st.text_input("INVERSOR", key="env_inv", value=st.session_state.get('edit_Kit_Enviado_-_Inversor', ''))
            with col3:
                st.subheader("Kit ATUAL Instalado")
                kit_atual_pot = st.text_input("POTÊNCIA", key="atual_pot", value=st.session_state.get('edit_Kit_ATUAL_-_Potência', ''))
                kit_atual_placa = st.text_input("PLACA", key="atual_placa", value=st.session_state.get('edit_Kit_ATUAL_-_Placa', ''))
                kit_atual_inversor = st.text_input("INVERSOR", key="atual_inv", value=st.session_state.get('edit_Kit_ATUAL_-_Inversor', ''))
            
            st.divider()
            comentario_notion = st.text_area("Comentário do Notion", value=st.session_state.get('edit_Comentário_Notion', ''))
            
            # --- Análise e Ação ---
            st.subheader("2. Análise e Ação")
            
            submitted = st.form_submit_button("Analisar e Salvar", use_container_width=True, type="primary")

            if submitted:
                pot_kit = parse_potencia_numerica(kit_atual_pot)
                pot_inv = parse_potencia_numerica(kit_atual_inversor)

                if not pot_kit or not pot_inv:
                    st.error("Potência do Kit ATUAL e do Inversor devem ser números válidos para análise.")
                else:
                    potencia_para_analise = min(pot_kit, pot_inv)
                    st.info(f"Análise considera a menor potência entre o kit ({pot_kit} kWp) e o inversor ({pot_inv} kWp): **{potencia_para_analise} kWp**")
                    
                    instrucao, status_sugerido = gerar_instrucao_tecnica(cidade, fase, carga_instalada_kw, potencia_para_analise, df_tensao, df_dados_tecnicos, mapa_ligacao)
                    st.session_state.instrucao = instrucao
                    st.session_state.status_sugerido = status_sugerido
                    
                    df_historico = pd.read_csv("atualizacoes_projetos.csv") if os.path.exists("atualizacoes_projetos.csv") else pd.DataFrame()
                    
                    novo_registro = {
                        "Cliente": cliente, "Data de Envio": data_envio.strftime('%Y-%m-%d'), "Status": status_sugerido, "Cidade": cidade, "Fase": fase, "Carga Instalada (kW)": carga_instalada_kw,
                        "Kit Instalado - Potência": kit_inst_pot, "Kit Instalado - Placa": kit_inst_placa, "Kit Instalado - Inversor": kit_inst_inversor,
                        "Kit Enviado - Potência": kit_env_pot, "Kit Enviado - Placa": kit_env_placa, "Kit Enviado - Inversor": kit_env_inversor,
                        "Kit ATUAL - Potência": kit_atual_pot, "Kit ATUAL - Placa": kit_atual_placa, "Kit ATUAL - Inversor": kit_atual_inversor,
                        "Comentário Notion": comentario_notion, "Instrução da Análise": instrucao.replace("__SEPARADOR__", "\n\n")
                    }

                    if edit_mode:
                        df_historico.loc[st.session_state.edit_index] = novo_registro
                        st.success("Registro atualizado com sucesso!")
                    else:
                        df_historico = pd.concat([df_historico, pd.DataFrame([novo_registro])], ignore_index=True)
                        st.success("Novo registro salvo com sucesso!")
                    
                    df_historico.to_csv("atualizacoes_projetos.csv", index=False)
                    st.rerun()

    # --- Exibição dos resultados fora do formulário ---
    if st.session_state.instrucao:
        instrucao = st.session_state.instrucao
        if "ERRO" in instrucao: st.error(instrucao)
        elif "__SEPARADOR__" in instrucao:
            partes = instrucao.split("__SEPARADOR__")
            st.error(partes[0]); st.info(partes[1])
        else: st.success(instrucao)
        
        if st.session_state.status_sugerido not in ["", "Erro de Análise"]:
            st.success(f"**Status definido e salvo automaticamente:** {st.session_state.status_sugerido}")


# --- Visualização do Histórico ---
st.divider()
st.header("📋 Histórico de Atualizações")
if os.path.exists("atualizacoes_projetos.csv"):
    df_historico = pd.read_csv("atualizacoes_projetos.csv")
    if 'Status' not in df_historico.columns: df_historico['Status'] = 'N/A'

    col_filter, col_clear = st.columns([3, 1])
    with col_filter:
        status_options = ["Todos"] + list(df_historico["Status"].unique())
        status_filter = st.selectbox("Filtrar por Status:", options=status_options)
    with col_clear:
        st.write("") # Espaçamento
        if st.button("Limpar Formulário / Novo Registro", use_container_width=True):
            clear_form()
            st.rerun()

    df_filtrado = df_historico if status_filter == "Todos" else df_historico[df_historico["Status"] == status_filter]

    for index, row in df_filtrado.iterrows():
        cliente_nome = str(row.get("Cliente", "N/A"))
        status_valor = str(row.get("Status", "N/A"))
        
        expander_title = f"{cliente_nome}  |  Status: {status_valor}"
        
        with st.expander(expander_title):
            st.button("Carregar para Edição", key=f"edit_{index}", on_click=load_record_for_edit, args=(df_historico, index))
            
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
            
            if "ERRO" in instrucao_texto:
                st.error(instrucao_texto)
            elif "REPROVADO" in instrucao_texto:
                partes = instrucao_texto.split("\n\n")
                st.warning(partes[0])
                if len(partes) > 1:
                    st.info("\n\n".join(partes[1:]))
            else:
                st.success(instrucao_texto)
else:
    st.info("Nenhum registro encontrado. Adicione um novo registro no formulário acima.")

st.caption("Desenvolvido por Vitória de Sales Sena ⚡")
