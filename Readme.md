Descripción de OpenAPI de la API REST de GitHub
Este repositorio contiene descripciones de OpenAPI para la API REST de GitHub .

¿Qué es OpenAPI?
De la especificación de OpenAPI :

La Especificación OpenAPI (OAS) define una descripción de interfaz estándar, independiente del lenguaje de programación para las API HTTP, que permite que tanto los humanos como las computadoras descubran y comprendan las capacidades de un servicio sin requerir acceso al código fuente, documentación adicional o inspección del tráfico de red. . Cuando se define correctamente a través de OpenAPI, un consumidor puede comprender e interactuar con el servicio remoto con una cantidad mínima de lógica de implementación. Similar a lo que han hecho las descripciones de interfaz para la programación de nivel inferior, la Especificación OpenAPI elimina las conjeturas al llamar a un servicio.

Estado del proyecto
Este proyecto se encuentra actualmente en BETA . Esperamos que esta descripción sea precisa, pero está en desarrollo activo . Si ha identificado una discrepancia entre el comportamiento de la API de GitHub y estas descripciones, abra un problema.

Formatos de descripción
Cada documento de OpenAPI está disponible en dos formatos: empaquetado y desreferenciado .

Las descripciones incluidas son artefactos de archivo único que hacen uso de los componentes de OpenAPI para su reutilización y portabilidad. Esta es la forma preferida de interactuar con la descripción de OpenAPI de GitHub.
Algunas herramientas tienen un soporte deficiente para referencias a componentes dentro del artefacto. Recomendamos encarecidamente buscar herramientas que admitan componentes referenciados, pero como eso no siempre es posible, también proporcionamos una versión completamente desreferenciada de la descripción, sin referencias.
Extensiones de proveedores
Usamos varias extensiones de proveedores para conceptos que son más difíciles de expresar con componentes de OpenAPI y / o que son específicos de GitHub. Para obtener más información sobre las extensiones utilizadas en esta descripción, consulte extensions.md

Limitaciones
No todos los encabezados se describen en los documentos de OpenAPI, espere que se agreguen con el tiempo.
Ciertos recursos de la API de GitHub utilizan parámetros de ruta de varios segmentos, que no son compatibles con la especificación de OpenAPI. Por el momento, hemos anotado dichos parámetros con una x-multi-segmentextensión. En general, la codificación URL de esos parámetros es una buena idea.
Muchas de las operaciones descritas en estos documentos son accesibles a través de múltiples rutas. Por el momento, hemos descrito la forma más común de acceder a estas operaciones, pero estamos trabajando en una forma de describir las rutas de alias y / o describir todas las rutas posibles.
Este repositorio solo contiene las versiones empaquetadas y desreferenciadas de nuestras descripciones de API REST. Estamos buscando ofrecer una estructura de directorio con referencias completas para una navegación más sencilla.
Contribuyendo
Debido a que esta descripción se usa en toda la experiencia de desarrollo de API de GitHub, actualmente no aceptamos solicitudes de extracción que modifiquen directamente la descripción. Este repositorio se mantiene actualizado automáticamente con la descripción utilizada para validar las solicitudes de la API de GitHub, así como para impulsar las pruebas de contrato. Consulte CONTRIBUTING.md para obtener más detalles.

Licencia
github / rest-api-description tiene licencia de MIT

Contacto
Puede ponerse en contacto con opensource+rest-api-description@github.com con cualquier pregunta relacionada con este repositorio.
