import streamlit as st
import re,json,os
import time
from langdetect import detect
from PyPDF2 import PdfReader
from io import StringIO,BytesIO
from docx import Document
from langchain.chat_models import ChatOpenAI
from docx.shared import RGBColor 
from langchain_text_splitters import RecursiveCharacterTextSplitter
import weaviate,tiktoken
from weaviate.classes.init import Auth
import weaviate.classes as wvc
from weaviate.classes.config import Configure, Property, DataType, Tokenization
from weaviate.classes.query import Filter, MetadataQuery



api_keys = {
    'openai_api_key': os.getenv('OpenAI_key'),
    'weaviate_URL':"https://7blppfh7swc9z87xon9sq.c0.europe-west3.gcp.weaviate.cloud", # type: ignore
    'weaviate_api_key':"x6obKaLeKk2PX0KmiAUaFE8MeV3sZDSWNNfP"
}
def get_llm(model,api_keys):
    return ChatOpenAI(
    temperature=0,
    model=model,
    openai_api_key= api_keys['openai_api_key'],
    verbose=True
)

@st.cache_data
def get_fe_dict(language):
    multilingual_frontend= {
        'it':{
            'warning':'Oops, sembra che qualcosa sia andato storto 😞',
            'bibliography':['Bibliografia','BIBLIOGRAFIA'],
            'index':['Indice','INDICE','CONTENUTI','Contenuti','Sommario','SOMMARIO'],
            'setting':"⚙️ Opzioni",
            'language':'Lingua',
            'resources':'📚 Gestisci Risorse',
            'upload':{'pdf': 'Carica Normative in .pdf','word':'Carica i tuoi documenti in .docx'},
            'res_list':'Risorse caricate:',
            'results':'✒️ Risultati',
            'topic':"Argomento dell'Audit",
            'help':'❓ Aiuto',
            'confirm':"L'output dell'Audit è chiaro?",
            "status":{'YES':'Conforme','NO':'Non conforme'},
            'help_txt':"""Ciao, per utilizzare al meglio l'auditor devi sapere che ci sono due modalità: Full Document Audit e Chapter Audit.\n\n Per il Full Document Audit, devi solamente scrivere un argomento su cui fare l'Audit e dopo ci pensa l'LLM. Ricordati che non devi scrivere come se dietro ci fosse una persona a rispondere, ma cose semplici come "Sicurezza fisica del luogo di lavoro", "Analisi del contesto" etc. \n\n Il Chapter Audit funziona come il Full Document Audit, però invece che cercare i chunk del documento in base a quello che hai scritto, puoi dirgli direttamente quali capitoli deve utilizzare""",
            'noncs':"Sono state rilevate non conformità per quanto riguarda:\n"
        },
        'en':{
            'warning': 'Oops, it looks like something went wrong 😞',
            'bibliography':['Bibliography','BIBLIOGRAPHY'],
            'index':['Index','INDEX','Content','CONTENT'],
            'setting':'⚙️ Settings',
            'language':'Language',
            'resources':'📚 Manage Resources',
            'upload':{'pdf':'Upload Norms in .pdf','word':'Upload your documents in .docx'},
            'res_list':'Uploaded resources:',
            'results':'✒️ Results',
            'topic':'Audit Topic',
            'help':'❓ Help',
            'confirm':'Is the output of the audit understandable?',
            'noncs':'Non conformities have been detected for what concerns: \n',
            'status':{'YES':'Compliant','NO':'Not compliant'},
            'help_txt':"""Hey, to use this Auditor properly, you have to know that you can perform two kinds of Audit: the Full Document Audit and the Chapter Audit.\n\n As for the Full Document Audit, you just need to write a topic to Audit on and then the LLM will do all the work. Remember you don't have to write as if there was a human behind it, but something simple, like "Workplace security","Context Analysis" and so on. \n\n The Chapter Audit works in a similar way to the Full Document Audit, but instead of looking for chunks based on similarity to what you wrote, it allows you to feed the LLM all the chapters you want to use"""
        },
        'eml':{
            'warning':"Oops, al pèr c'a'i séppa un quél ed sbalers",
            'setting':"⚙️ Selt",
            'language':'Léngua',
            'resources':"📚 Tgnér dré a'l risours",
            'upload':{'pdf':"Tira só na norma in .pdf",'word':'Tira só i tó document in .docx'},
            'res_list':'Risours bel e tirè só',
            'results':'✒️ Zgatt',
            'topic':"Argument d'l'Audit",
            'help':'❓ Ajud',
            'confirm':"Capéss'al tutt d'l'Audit?",
            'status':{'YES':'Fat pulid','NO':'briza compliant'},
            'noncs':"Óna non conformitè l'è stè bele truvè in vètta a:",
            'help_txt':"""Ciao, par druvèr mej c'a's pol st'Auditor qué t'e da saveir c'a i'e dou modalitè: Full Document e Chapter Audit.\n\n Pr al Full Document t'e soul da scrévvr ón argument da fèr'i l'Audit e dopp a'i pensa ló. Arcord'et c't'e mégga da scrévvr ón quél cum s'a'i foss óna parsona dré ad arsponder, mo ón quél polleg e fasil, cumpagn a "Sicurezza fisica del luogo di lavoro", "Analisi del contesto" etc.\n\n Al Chapter Audit l'è presiz cum al Full Document Audit, parò invesi che sarcher i chunk d'al document par truvèr i qui cumpagn a l'argument c't'e scrétt té, a's pol dir'i capitolo da druvèr!"""
        }
    }
    return multilingual_frontend[language]

def end_audit(lang='en'):
    doc=Document()
    for au in st.session_state.audit_results:
        res_text=[]
        for d in au['chapters']:
            for k,v in d:
                text=f'{k}: '
                text+='\t'.join(v)
                res_text.append(text)
        res_fin='\t'.join(res_text)
        head=f"""Audit: {res_fin}"""
        doc.add_heading(head,1)
    return doc

def get_token_length(text):
        return len(tiktoken.encoding_for_model("gpt-3.5-turbo").encode(text))

def connect_wc(api_keys):
    return weaviate.connect_to_weaviate_cloud(
            cluster_url=api_keys['weaviate_URL'],
            auth_credentials=Auth.api_key(api_keys['weaviate_api_key']),
            headers={
            "X-OpenAI-Api-Key": api_keys['openai_api_key']
            }
        )

def clean_weaviate(api_keys):
    wc_client=connect_wc(api_keys)
    if wc_client.collections.exists('Docchunk'):
        wc_client.collections.delete('Docchunk')


    wc_client.collections.create(
        'Docchunk',
        vectorizer_config=Configure.Vectorizer.text2vec_openai(),
        properties=[
            Property(
                name='content', 
                data_type=DataType.TEXT
                ),
            Property(
                name='chunk_id', 
                data_type=DataType.INT,
                skip_vectorization=True
                ),
            Property(
                name='chapter', 
                data_type=DataType.TEXT,
                skip_vectorization=True
                ),
            Property(
                name='document_name', 
                data_type=DataType.TEXT,
                skip_vectorization=True
                )
        ]
    )

def add_a_resource_weaviate(file,api_keys=api_keys):
        wc_client=connect_wc(api_keys)
        d=get_pdf_dict(file)
        s=sections(d)
        for k,v in s.items():
            text_splitter = RecursiveCharacterTextSplitter(
                chunk_size=250,
                chunk_overlap=20,
                length_function=get_token_length,
                is_separator_regex=False,
            )
            chunks = text_splitter.create_documents([v])
            coll=wc_client.collections.get("Docchunk")
            for i in range(len(chunks)):
                try:
                    coll.data.insert({
                        "content":chunks[i].page_content,
                        "chunk_id":i+1,
                        'chapter':k,
                        'document_name':file.name
                        })
                except:
                    count = 0
                    for item in coll.iterator():
                        count += 1
                    st.warning(f"Nella collezione ci sono {count} elementi")

def load_files(files,api_keys):
    clean_weaviate(api_keys)
    for f in files:
        add_a_resource_weaviate(f,api_keys)

def del_res_where(weaviate_collection,doc_name):
    weaviate_collection.data.delete_many(
                        where=Filter.by_property("document_name").like(doc_name)
                    )

def understood_button(l,d):
    l.append(d)
    	
def lang_detect(pdf):
    txt=' '.join([p.extract_text() for p in PdfReader(pdf).pages])
    return detect(txt)

def find_index(pg:list,lang='en'):
    multidict=get_fe_dict(lang)
    b=multidict['bibliography']
    i=multidict['index']
    idx_pg="Not found"
    ix="Not found"
    for p in pg:
        for el in i:
            if el in p:
                for bl in b:
                    if bl in p:
                        idx_pg=p
                        ix=pg.index(p)
                        break
                    elif bl in pg[pg.index(p)+1]:
                        idx_pg=p+pg[pg.index(p)+1]
                        ix=pg.index(p)+1
                        break
    return idx_pg,ix

def extract_sections(idx_pg,lang='en'):
    lines=re.findall(r"\d+\.?\d?\.?\d?\s+[A-Za-z\s'àèìòùéÀÈÌÒÙÉ]+",idx_pg)
    lines=[l.strip(' ') for l in lines]
    b=get_fe_dict(lang)['bibliography']
    for bl in b:
        if [l for l in lines if bl in l]:
            lines=lines[:lines.index([l for l in lines if bl in l][0])]
            lines=[l.split('\n')[1] if len(l.split('\n'))>1 else l for l in lines]
    lines_2=[re.sub(r'(\s)([a-zA-Z])(\s)([a-zA-Z])',r'\2\4',l) for l in lines if l]
    return lines_2

def preprocess(text):
    regex = r'[!\'#\$%&\'\(\)\*\+,-\./:;<=>\?@\[\\\]\^_`{\|}~]{2,}'
    txt = re.sub(regex, '', text)
    txt=re.sub(r'(\s)([a-zA-Z])(\s)([a-zA-Z])',r'\2\4',txt)
    return txt

def get_pdf_dict(file):
    pdf_dict={}
    ling=lang_detect(file)
    ix_pg,ix=find_index([p.extract_text() for p in PdfReader(file).pages],lang=ling)
    if ix!='Not found':
        pdf_dict['ix_pg']=ix_pg
        pdf_dict['ix']=ix
        pdf_dict['pages']=[p.extract_text() for p in PdfReader(file).pages]
        pdf_dict['lang']=ling
    return pdf_dict

def sections(pdf_dict):
        l=pdf_dict['lang']
        b=get_fe_dict(l)
        pages = pdf_dict['pages']
        maps={}
        if pdf_dict['ix']!='Not found':
            text_pages=pages[pdf_dict['ix']+1:]
            scs=extract_sections(pdf_dict['ix_pg'],lang=l)
            l2=[l for l in scs if l in '\n'.join(text_pages)]
            ixs=[l2.index(s) for s in l2 if l2.index(s)+1!=len(l2)]
            txt='\n'.join(text_pages)

            for i in ixs:
                head=l2[i]
                next_head=l2[i+1]
                if txt.split(head):
                    if len(txt.split(head))>1:
                        maps[head]=preprocess(txt.split(head)[1].split(next_head)[0])
            for el in b:
                if el in txt:
                    if len(txt.split(l2[-2])[1].split(l2[-1]))>1:
                        maps[l2[-1]]=preprocess(txt.split(l2[-2])[1].split(l2[-1])[1].split(el)[0])
        return maps

def weaviate_search(wc_client,topic,resource,chapters=None):
    collection=wc_client.collections.get("Docchunk")
    if chapters:
        for c in chapters:
            response = collection.query.near_text(
                                        query=topic,
                                        filters=(
                                            Filter.by_property("chapter").equal(c) |
                                            Filter.by_property("document_name").equal(resource)
                                        ),
                                        return_metadata=MetadataQuery(distance=True)
                                        )
    else:
        response = collection.query.near_text(
                            query=topic,
                            filters=Filter.by_property("document_name").equal(resource),
                            limit=3,
                            return_metadata=MetadataQuery(distance=True)
                            )
    return [r.properties['content'] for r in response.objects]

def full_document_audit(request,important_text,doc_text,llm,lang='en'):
    if lang=='eml':
        lang='it'
    request_topic=llm.predict(f"Given a {request}, extract the global topic of the request. Output the global topic and nothing more, in the original language of the question")
    norm_prompt=f"""Given a norm text, generate a list of points to be addressed to be compliant with said.
    The norm you need to analyse is:
    <norm text> 
        {important_text}
    </norm text>
    Output a json object with ONLY ONE KEY "output" and as its value an array listing the actions you rewrote."""
    llm.model_kwargs['response_format']={'type': 'json_object'}
    norm_list = json.loads(llm.predict(norm_prompt))['output']
    llm.model_kwargs.pop('response_format', None)
    if lang=='it':
        norm_dict={}
        for point in norm_list:
            norm_dict[point]=llm.predict(f'Translate {point} in italian. Make sure it is properly translated and only output the translation and nothing more')
    else:
        norm_dict={}
        for point in norm_list:
            norm_dict[point]=point
    #print(norm_list)

    non_conformities=[]
    for k,point in norm_dict.items():
        #If the point is NOT addressed, state that the point is not addressed and WHY.
        #Otherwise, state that it is addressed and if necessary output a judgment of how the point could be addressed better and WHY.
        gap_prompt=f"""You will be given a procedure and you have to check if the matter of {point} is addressed properly or not by the procedure.
            The procedure is:
            {doc_text}.
        Output a JSON object with the following structure:
        - output: A judgement wheter the point is addressed, not addressed properly or not addressed at all.
        - reason: The reason of the output, basically why it is addressed or not and how to better address it according to the norm, in {lang}.
        - conformity: YES if the output is positive, NO if the output is negative.
        
        Make sure the text is in {lang}"""
        llm.model_kwargs['response_format']={'type': 'json_object'}
        results = json.loads(llm.predict(gap_prompt))
        llm.model_kwargs.pop('response_format', None)
        results['point']=point
        non_conformities.append(results)
    

    return non_conformities


