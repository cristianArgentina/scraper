/**
 * Compacta el historial de precios: si una lectura es igual a la anterior
 * (mismo sitio + sku, mismo precio/disponibilidad/error), se descarta y
 * la lectura que se conserva guarda en "fecha_ultima_escritura" la fecha
 * de la última lectura repetida.
 *
 * NO modifica la hoja original: escribe el resultado en una hoja nueva.
 */
const CONFIG = {
  hojaOrigen: 'precios',               // nombre de tu hoja actual
  hojaDestino: 'precios_compactado',   // hoja nueva (se crea o se pisa)
  colFecha: 'fecha',
  colsClave: ['sitio', 'sku'],         // identifican "un producto en un comercio"
  colsComparar: ['precio', 'disponibilidad', 'error'], // si cambia alguna, es lectura nueva
  colNueva: 'fecha_ultima_escritura',
};

function compactarPrecios() {
  const ss = SpreadsheetApp.getActive();
  const origen = ss.getSheetByName(CONFIG.hojaOrigen);
  if (!origen) throw new Error('No existe la hoja: ' + CONFIG.hojaOrigen);

  const datos = origen.getDataRange().getValues();
  const encabezado = datos.shift();
  const idx = (nombre) => {
    const i = encabezado.indexOf(nombre);
    if (i < 0) throw new Error('Falta la columna: ' + nombre);
    return i;
  };
  const iFecha = idx(CONFIG.colFecha);
  const iClave = CONFIG.colsClave.map(idx);
  const iComp = CONFIG.colsComparar.map(idx);

  // Fecha como número para ordenar (acepta Date o texto "2026-08-03 22:28")
  const ts = (v) => v instanceof Date ? v.getTime() : new Date(String(v).replace(' ', 'T')).getTime();

  // Orden cronológico (sort estable, así que empates conservan el orden original)
  datos.sort((a, b) => ts(a[iFecha]) - ts(b[iFecha]));

  const salida = [];
  const ultimo = new Map(); // clave -> { firma, pos } de la última lectura conservada

  for (const fila of datos) {
    const clave = iClave.map((i) => String(fila[i])).join('|');
    const firma = iComp.map((i) => String(fila[i])).join('|');
    const prev = ultimo.get(clave);

    if (prev && prev.firma === firma) {
      // Repetida: no se guarda, solo se extiende la fecha de la lectura conservada
      salida[prev.pos][encabezado.length] = fila[iFecha];
    } else {
      salida.push([...fila, fila[iFecha]]);
      ultimo.set(clave, { firma, pos: salida.length - 1 });
    }
  }

  // Escritura en hoja nueva
  let destino = ss.getSheetByName(CONFIG.hojaDestino);
  if (destino) destino.clear(); else destino = ss.insertSheet(CONFIG.hojaDestino);

  const nuevoEncabezado = [...encabezado, CONFIG.colNueva];
  destino.getRange(1, 1, 1, nuevoEncabezado.length).setValues([nuevoEncabezado]);
  if (salida.length) {
    destino.getRange(2, 1, salida.length, nuevoEncabezado.length).setValues(salida);
    // La columna nueva usa el mismo formato de fecha que la original
    const fmt = origen.getRange(2, iFecha + 1).getNumberFormat();
    destino.getRange(2, iFecha + 1, salida.length, 1).setNumberFormat(fmt);
    destino.getRange(2, nuevoEncabezado.length, salida.length, 1).setNumberFormat(fmt);
  }
  destino.setFrozenRows(1);

  const msg = `Filas originales: ${datos.length} → conservadas: ${salida.length} ` +
              `(eliminadas: ${datos.length - salida.length})`;
  Logger.log(msg);
  ss.toast(msg, 'Compactación lista', 10);
}
