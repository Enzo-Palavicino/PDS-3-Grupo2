from app.nucleo.campos import CAMPOS_ATENCION, CAMPOS_LISTA, ETIQUETAS
from app.nucleo.extraccion import RegistroExtraido

# Lo que devuelve la IA y no es un campo del registro.
NO_SON_CAMPOS = {"es_consulta", "ambiguedades"}


def test_todo_lo_que_extrae_la_ia_tiene_nombre_y_etiqueta():
    # Si la extracción agrega un campo (por ejemplo, en E3-05), tiene que estar en campos.py.
    extraidos = set(RegistroExtraido.model_fields) - NO_SON_CAMPOS

    assert extraidos <= set(CAMPOS_ATENCION)


def test_la_especialidad_es_un_campo_aunque_no_la_extraiga_la_ia():
    assert "especialidad" in ETIQUETAS


def test_los_campos_lista_coinciden_con_las_listas_de_la_extraccion():
    listas = {
        nombre
        for nombre, campo in RegistroExtraido.model_fields.items()
        if campo.annotation is not None and getattr(campo.annotation, "__origin__", None) is list
    } - NO_SON_CAMPOS

    assert listas <= CAMPOS_LISTA
