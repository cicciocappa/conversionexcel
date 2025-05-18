# app.py
from flask import Flask, render_template, request, send_file
import xlsxwriter
import io
import os
import datetime
import math # Per math.floor, sebbene timedelta sia più diretto

# --- Costanti e Helper per crea_excel ---
LABVIEW_EPOCH = datetime.datetime(1904, 1, 1, 0, 0, 0, 0, tzinfo=datetime.timezone.utc)

# Indici delle colonne da estrarre dal file CSV (0-based)
# COLUMNS_TO_KEEP_INDICES = [0, 1, 3] # ts_rel, V_mV, Temp_C
TIMESTAMP_COL_IDX = 0
TENSIONE_COL_IDX = 1
TEMPERATURA_COL_IDX = 3 # La terza colonna da tenere è all'indice 3

# Nomi delle colonne per il file Excel
NEW_COLUMN_NAMES = ['timestamp', 'tensione (mV)', 'temperatura (°C)']

app = Flask(__name__)

def _convert_labview_ts_to_datetime(ts_float: float) -> datetime.datetime | None:
    """
    Converte un timestamp LabVIEW (float, secondi dall'epoca LabVIEW)
    in un oggetto datetime Python naive (senza timezone esplicita per xlsxwriter).
    Restituisce None in caso di errore di conversione.
    """
    try:
        # datetime.timedelta gestisce correttamente la parte intera e frazionaria dei secondi
        event_time_utc = LABVIEW_EPOCH + datetime.timedelta(seconds=ts_float)
        # Per xlsxwriter, è spesso meglio passare datetime naive se non si gestiscono
        # specificamente le timezone nel file Excel. Convertiamo a naive se era aware.
        if event_time_utc.tzinfo:
            event_time_naive = event_time_utc.astimezone(datetime.timezone.utc).replace(tzinfo=None)
            return event_time_naive
        return event_time_utc # Già naive (improbabile con LABVIEW_EPOCH UTC)
    except (ValueError, TypeError, OverflowError) as e:
        # print(f"Warning: Errore durante la conversione del timestamp {ts_float} a datetime: {e}")
        return None

def _process_numeric_value_str(value_str: str) -> str:
    """
    Processa una stringa che rappresenta un valore numerico:
    - Rimuove spazi bianchi iniziali/finali.
    - Rimuove caratteri '-' iniziali/finali (come da script originale `np.char.strip(value, chars='-')`).
    - Sostituisce la virgola con il punto come separatore decimale.
    - Se c'è un punto decimale, rimuove gli zeri finali e un eventuale punto finale residuo.
    """
    if value_str is None:
        return ""
        
    s = str(value_str).strip()  # Rimuove spazi bianchi
    
    # Questa riga replica il comportamento di np.char.strip(values, chars='-')
    # che rimuove '-' sia all'inizio che alla fine della stringa.
    # Se l'intenzione è mantenere i numeri negativi, questa logica andrebbe cambiata.
    # Per ora, replichiamo lo script fornito.
    s = s.strip('-')
    
    s = s.replace(',', '.')     # Sostituisce la virgola con il punto

    # Applica rstrip solo se c'è un punto decimale
    if '.' in s:
        # Rimuove gli zeri finali
        processed_s = s.rstrip('0')
        # Se dopo aver rimosso gli zeri rimane un punto alla fine, rimuovilo
        if processed_s.endswith('.'):
            processed_s = processed_s.rstrip('.')
        return processed_s
    return s # Ritorna la stringa processata se non c'era punto o dopo la pulizia

# --- Funzione crea_excel aggiornata ---
def crea_excel(file_content_str: str, original_filename: str):
    """
    Crea un file Excel processando il contenuto di un file di testo (tipo CSV).
    Scrive timestamp come oggetti datetime e valori numerici come float.
    Aggiunge un grafico scatter con due assi Y per tensione e temperatura vs tempo.
    """
    print(f"Inizio processamento Excel con grafico per: {original_filename}")

    base_name, _ = os.path.splitext(original_filename)
    excel_filename = f"{base_name}.xlsx"

    output_stream = io.BytesIO()
    # Opzione 'default_date_format' è utile per le celle, ma il grafico usa i valori numerici sottostanti
    workbook = xlsxwriter.Workbook(output_stream, {'in_memory': True, 'remove_timezone': True, 'default_date_format': 'yyyy-mm-dd hh:mm:ss.000'})
    worksheet = workbook.add_worksheet() # Nome di default 'Sheet1'

    # --- Formati per le celle ---
    date_format = workbook.add_format({'num_format': 'yyyy-mm-dd hh:mm:ss.000', 'align': 'left'})
    header_format = workbook.add_format({'bold': True, 'bg_color': '#DDEBF7', 'border': 1})
    # Potresti voler definire un number_format per i float se vuoi un controllo preciso
    # number_format = workbook.add_format({'num_format': '0.00'})

    # --- Scrittura Intestazioni Tabella ---
    for col_num, header_title in enumerate(NEW_COLUMN_NAMES):
        worksheet.write(0, col_num, header_title, header_format)
    worksheet.freeze_panes(1, 0)

    # --- Processamento e Scrittura Dati ---
    row_num = 1  # Inizia dalla riga 1 (0-indexed) per i dati
    lines_processed_count = 0
    lines_error_count = 0
    max_data_row = 0 # Terrà traccia dell'ultima riga con dati validi per il grafico

    file_lines = file_content_str.splitlines()

    for line_content in file_lines:
        current_line_has_valid_data_for_graph = True # Flag per questa riga
        line_content = line_content.strip()
        if not line_content:
            continue

        try:
            parts = line_content.split(';')
            if len(parts) < max(TIMESTAMP_COL_IDX, TENSIONE_COL_IDX, TEMPERATURA_COL_IDX) + 1:
                lines_error_count += 1
                continue

            # 1. Timestamp (Colonna A)
            datetime_obj = None
            raw_timestamp_str = parts[TIMESTAMP_COL_IDX]
            try:
                timestamp_float = float(raw_timestamp_str.replace(',', '.'))
                datetime_obj = _convert_labview_ts_to_datetime(timestamp_float)
            except ValueError:
                lines_error_count += 1
                current_line_has_valid_data_for_graph = False

            if datetime_obj:
                worksheet.write_datetime(row_num, 0, datetime_obj, date_format)
            else:
                worksheet.write_string(row_num, 0, "Timestamp Invalido")
                current_line_has_valid_data_for_graph = False


            # 2. Tensione (mV) (Colonna B)
            raw_tensione_str = parts[TENSIONE_COL_IDX]
            processed_tensione_str = _process_numeric_value_str(raw_tensione_str)
            try:
                tensione_val = float(processed_tensione_str)
                worksheet.write_number(row_num, 1, tensione_val) # Potresti usare number_format
            except (ValueError, TypeError):
                worksheet.write_string(row_num, 1, processed_tensione_str)
                lines_error_count +=1
                current_line_has_valid_data_for_graph = False

            # 3. Temperatura (°C) (Colonna C)
            raw_temperatura_str = parts[TEMPERATURA_COL_IDX]
            processed_temperatura_str = _process_numeric_value_str(raw_temperatura_str)
            try:
                temperatura_val = float(processed_temperatura_str)
                worksheet.write_number(row_num, 2, temperatura_val) # Potresti usare number_format
            except (ValueError, TypeError):
                worksheet.write_string(row_num, 2, processed_temperatura_str)
                lines_error_count +=1
                current_line_has_valid_data_for_graph = False

            if current_line_has_valid_data_for_graph:
                 max_data_row = row_num # Aggiorna l'ultima riga valida per il grafico
            
            row_num += 1
            lines_processed_count += 1

        except Exception as e:
            # print(f"Errore critico durante il processamento della riga '{line_content}': {e}")
            lines_error_count += 1
            # Continua con la riga successiva
    
    # --- Creazione Grafico ---
    # Solo se ci sono dati validi da graficare (almeno una riga oltre l'intestazione)
    if max_data_row >= 1: # max_data_row è 0-indexed, quindi >=1 significa almeno una riga di dati
        chart = workbook.add_chart({'type': 'scatter', 'subtype': 'straight_with_markers'}) # scatter con linee rette e marcatori
        # Alternativa: 'line' se l'asse X non è strettamente numerico/data (ma scatter è meglio per le date)

        chart.set_title({'name': 'Tensione e temperatura nel tempo'})
        chart.set_size({'width': 1000, 'height': 600})

        # Serie Dati Tensione (Blu)
        # worksheet.name è 'Sheet1' (o il nome che dai al foglio)
        # Formato: '=Sheet1!$Colonna$RigaInizio:$Colonna$RigaFine'
        # Le righe sono 1-indexed per le formule Excel, ma max_data_row è 0-indexed
        # quindi usiamo max_data_row + 1
        
        # Assicurati che i riferimenti alle celle siano corretti.
        # Le categorie (asse X) sono nella colonna A (indice 0), dalla riga 2 (indice 1) a max_data_row + 1
        # I valori di tensione (asse Y1) sono nella colonna B (indice 1)
        # I valori di temperatura (asse Y2) sono nella colonna C (indice 2)

        # Nota: Per i grafici, i riferimenti alle righe nelle formule sono 1-based.
        # La nostra `max_data_row` è 0-based e punta all'ultima riga con dati.
        # Quindi l'ultima riga per la formula sarà `max_data_row + 1`.
        # La prima riga di dati è la riga 2 (1-based), che corrisponde a `row_num = 1` (0-based).

        # Serie Tensione (blu)
        chart.add_series({
            'name':       f"='{worksheet.name}'!$B$1",  # Nome dalla cella di intestazione B1
            'categories': f"='{worksheet.name}'!$A$2:$A${max_data_row + 1}", # Timestamp (X)
            'values':     f"='{worksheet.name}'!$B$2:$B${max_data_row + 1}", # Tensione (Y1)
            'line':       {'color': 'blue'},
            'marker':     {'type': 'none'}, # o 'circle', 'square', etc.
            'y2_axis':    0, # Usa il primo asse Y (quello di sinistra)
        })

        # Serie Temperatura (rossa)
        chart.add_series({
            'name':       f"='{worksheet.name}'!$C$1",  # Nome dalla cella di intestazione C1
            'categories': f"='{worksheet.name}'!$A$2:$A${max_data_row + 1}", # Timestamp (X) - stessa categoria
            'values':     f"='{worksheet.name}'!$C$2:$C${max_data_row + 1}", # Temperatura (Y2)
            'line':       {'color': 'red'},
            'marker':     {'type': 'none'},
            'y2_axis':    1, # Usa il secondo asse Y (quello di destra)
        })

        # Impostazioni Assi
        chart.set_x_axis({
            'name': 'Tempo',
            'date_axis': True, # Indica che l'asse X è una data
            'major_gridlines': {'visible': True, 'line': {'dash_type': 'dash'}},
            # Puoi aggiungere 'num_format' se vuoi forzare un formato specifico sull'asse X
            'num_format': 'dd hh:mm', # Esempio
            'major_tick_mark': 'cross', # o 'inside', 'outside'
            'minor_tick_mark': 'none'
        })

        chart.set_y_axis({
            'name': 'Tensione (mV)',
            'major_gridlines': {'visible': True, 'line': {'dash_type': 'long_dash'}},
            'line': {'color': 'blue'} # Colore della linea dell'asse Y1
        })
        
        # Impostazioni per il secondo asse Y (Y2)
        chart.set_y2_axis({
            'name': 'Temperatura (°C)',
            'major_gridlines': {'visible': False}, # Opzionale, per non sovraffollare
            'line': {'color': 'red'} # Colore della linea dell'asse Y2
        })
        
        chart.set_legend({'position': 'top'}) # Posizione legenda

        # Inserisci il grafico nel foglio di lavoro
        worksheet.insert_chart('E1', chart) # Inserisci il grafico a partire dalla cella E1
    else:
        print("Nessun dato valido trovato per generare il grafico.")


    # --- Finalizzazione ---
    # Regola larghezza colonne per leggibilità
    worksheet.set_column('A:A', 23) # Timestamp
    worksheet.set_column('B:B', 15) # Tensione
    worksheet.set_column('C:C', 18) # Temperatura

    print(f"Processamento Excel con grafico completato per: {excel_filename}")
    print(f"Righe processate con successo: {lines_processed_count}, Righe con errori/saltate: {lines_error_count}")

    workbook.close()
    output_stream.seek(0)
    return output_stream, excel_filename

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload_file_route():
    if 'file' not in request.files:
        return "Nessun file inviato nella richiesta.", 400

    file = request.files['file']

    if file.filename == '':
        return "Nessun file selezionato.", 400

    if file:
        original_filename = file.filename
        print(f"File ricevuto: {original_filename}")

        # Legge il contenuto del file come testo
        # È importante gestire correttamente la codifica
        try:
            # Prova con UTF-8 che è molto comune
            file_content_str = file.read().decode('utf-8')
        except UnicodeDecodeError:
            # Se fallisce, prova con latin-1 (o cp1252), comune in Windows
            file.seek(0) # Riavvolgi il file stream prima di rileggerlo
            try:
                file_content_str = file.read().decode('latin-1')
            except UnicodeDecodeError:
                # Se anche questo fallisce, ritorna un errore
                return "Impossibile decodificare il file. Assicurarsi che sia un file di testo (UTF-8 o Latin-1).", 400
        except Exception as e:
            return f"Errore durante la lettura del file: {str(e)}", 500


        # Chiama la funzione placeholder per creare l'Excel
        excel_stream, excel_filename = crea_excel(file_content_str, original_filename)

        # Invia il file Excel all'utente
        return send_file(
            excel_stream,
            as_attachment=True,
            download_name=excel_filename, # Nome del file che l'utente vedrà
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )

    return "Errore sconosciuto durante l'upload.", 500

if __name__ == '__main__':
     app.run(debug=True, host='0.0.0.0', port=5000)
