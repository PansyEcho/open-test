"""验证真实二进制依赖的Spring装配、Repository映射及泛型契约，不启动容器。"""

from pathlib import Path
import subprocess
import zipfile

import pytest

from opentest.adapters.java_dependencies import JavaDependencyCatalog, MavenArtifact
from opentest.adapters.dependency_interfaces import DependencyInterfaceScanner
from opentest.adapters.dsf_operations import DsfSourceDiscoverer
from opentest.domain.models import DsfOperationDefinition, SourceReference


@pytest.fixture
def dependency_project(tmp_path):
    """构建只有binary JAR的隔离依赖，包含装配注解、Repository和继承泛型DTO。"""

    sources = {
        'org/springframework/stereotype/Service.java': 'package org.springframework.stereotype; import java.lang.annotation.*; @Retention(RetentionPolicy.RUNTIME) public @interface Service {}',
        'org/springframework/context/annotation/Configuration.java': 'package org.springframework.context.annotation; import java.lang.annotation.*; @Retention(RetentionPolicy.RUNTIME) public @interface Configuration {}',
        'org/springframework/context/annotation/ImportResource.java': 'package org.springframework.context.annotation; import java.lang.annotation.*; @Retention(RetentionPolicy.RUNTIME) public @interface ImportResource {String[] value();}',
        'org/springframework/boot/autoconfigure/condition/ConditionalOnProperty.java': 'package org.springframework.boot.autoconfigure.condition; import java.lang.annotation.*; @Retention(RetentionPolicy.RUNTIME) public @interface ConditionalOnProperty {String[] name(); String havingValue();}',
        'javax/ws/rs/Path.java': 'package javax.ws.rs; import java.lang.annotation.*; @Retention(RetentionPolicy.RUNTIME) public @interface Path {String value();}',
        'demo/api/Base.java': 'package demo.api; public class Base<T> { private String traceId; private T value; }',
        'demo/api/Request.java': 'package demo.api; public class Request extends Base<java.util.List<Item>> { private Long orderId; }',
        'demo/api/Item.java': 'package demo.api; public class Item { private String code; }',
        'demo/api/Remote.java': 'package demo.api; public interface Remote { @javax.ws.rs.Path("query") Request query(Request request); @javax.ws.rs.Path("update") Request update(Request request); @javax.ws.rs.Path("update") Request update(String request); }',
        'demo/client/Repository.java': 'package demo.client; public interface Repository { demo.api.Request find(demo.api.Request request); }',
        'demo/client/RepositoryImpl.java': 'package demo.client; @org.springframework.stereotype.Service public class RepositoryImpl implements Repository { private demo.api.Remote remote; public demo.api.Request find(demo.api.Request request) { return remote.query(request); } }',
        'demo/config/AutoConfig.java': 'package demo.config; @org.springframework.context.annotation.Configuration @org.springframework.context.annotation.ImportResource({"classpath:client.xml"}) @org.springframework.boot.autoconfigure.condition.ConditionalOnProperty(name={"demo.enabled"}, havingValue="true") public class AutoConfig {}',
    }
    java_root = tmp_path / 'java'
    classes = tmp_path / 'classes'
    classes.mkdir()
    paths = []
    for name, text in sources.items():
        path = java_root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        paths.append(str(path))
    # javac只生成测试fixture的类；static初始化器和Spring容器从不运行。
    subprocess.run(['javac', '-d', str(classes), *paths], check=True, capture_output=True)
    repository = tmp_path / 'maven'
    binary = repository / 'demo/client/1/client-1.jar'
    binary.parent.mkdir(parents=True)
    with zipfile.ZipFile(binary, 'w') as archive:
        for path in classes.rglob('*.class'):
            archive.write(path, path.relative_to(classes).as_posix())
        archive.writestr('client.xml', '<beans xmlns:context="http://www.springframework.org/schema/context"><context:component-scan base-package="demo.client.*"/></beans>')
        archive.writestr('META-INF/spring/org.springframework.boot.autoconfigure.AutoConfiguration.imports', 'demo.config.AutoConfig\n')
    root = tmp_path / 'project'
    source = root / 'src/main/java/demo/Use.java'
    source.parent.mkdir(parents=True)
    source.write_text('package demo; import demo.client.Repository; public class Use { private Repository repository; public void run() { repository.find(null); } }')
    catalog = JavaDependencyCatalog(repository)
    artifact = MavenArtifact('demo:client:1', binary, binary.with_name('client-1-sources.jar'))
    catalog._resolved[root] = [artifact], []
    return root, catalog, artifact


def test_jar_import_maps_repository_to_real_boundary(dependency_project):
    """显式JAR XML导入激活组件并映射封装；请求保留继承、泛型及嵌套字段。"""

    root, catalog, _ = dependency_project
    xml = root / 'src/main/resources/root.xml'
    xml.parent.mkdir(parents=True)
    xml.write_text('<beans><import resource="classpath*:client.xml"/></beans>')
    scanner = DependencyInterfaceScanner(root, {}, catalog)
    resources = scanner.resources()
    assert any(repository == 'demo:client:1' and path == 'client.xml' for repository, path, _ in resources)
    operation = DsfOperationDefinition(operation_id='dsf:remote:trade:query', provider_system_id='remote',
        gs_name='dsf.remote', service_name='trade', version='1', action='query',
        source_refs=[SourceReference(path='reference.xml', symbol='demo.api.Remote#query', line=1)])
    discovered = scanner.enrich([operation])[0]
    assert discovered.wrapper_symbols == ['demo.client.Repository#find']
    properties = discovered.request_schema['properties']
    assert properties['traceId']['type'] == 'string'
    assert properties['value']['items']['properties']['code']['type'] == 'string'
    assert any(ref.symbol == 'demo.client.RepositoryImpl#find' for ref in discovered.source_refs)


@pytest.mark.parametrize('enabled', ['true', 'false'])
def test_boot_imports_obey_conditions_without_loading_classes(dependency_project, enabled):
    """AutoConfiguration.imports只在Boot与属性条件成立时激活，不误扫整个JAR。"""

    root, catalog, _ = dependency_project
    boot = root / 'src/main/java/demo/Boot.java'
    boot.write_text('@SpringBootApplication class Boot {}')
    scanner = DependencyInterfaceScanner(root, {'demo.enabled': enabled}, catalog)
    resources = scanner.resources()
    assert any(path == 'client.xml' for _, path, _ in resources) == (enabled == 'true')
    assert ('demo.client.RepositoryImpl' in scanner._components) == (enabled == 'true')


def test_unused_jar_configuration_does_not_register(dependency_project):
    """存在依赖和调用签名不足以激活未导入的配置，未解析调用作为缺口保留。"""

    root, catalog, _ = dependency_project
    scanner = DependencyInterfaceScanner(root, {}, catalog)
    assert scanner.resources() == []
    assert scanner.enrich([]) == []
    assert any('demo.client.Repository#find' in gap for gap in scanner.gaps)


def test_maven_classpath_keeps_transitive_version_and_order(tmp_path, monkeypatch):
    """使用Maven实际选择的传递版本和classpath顺序，不挑选本机其他版本。"""

    root = tmp_path / 'project'
    root.mkdir()
    (root / 'pom.xml').write_text('<project><modelVersion>4.0.0</modelVersion><groupId>demo</groupId><artifactId>app</artifactId><version>1</version></project>')
    repository = tmp_path / 'maven'
    jars = [repository / 'demo/transitive/2/transitive-2.jar', repository / 'demo/direct/1/direct-1.jar']
    for jar in jars:
        jar.parent.mkdir(parents=True)
        with zipfile.ZipFile(jar, 'w') as archive:
            archive.writestr('marker', 'fixture')

    def maven(command, **kwargs):
        """模拟Maven输出真实解析顺序；分析器不能在解析后重新按路径排序。"""

        output = next(argument.split('=', 1)[1] for argument in command if argument.startswith('-Dmdep.outputFile='))
        Path(output).write_text(':'.join(str(path) for path in jars))
        return subprocess.CompletedProcess(command, 0, '', '')

    monkeypatch.setattr(subprocess, 'run', maven)
    artifacts, gaps = JavaDependencyCatalog(repository).resolved_artifacts(root)
    assert [item.coordinate for item in artifacts] == ['demo:transitive:2', 'demo:direct:1']
    assert gaps == []


def test_web_bootstrap_does_not_activate_unused_project_xml(dependency_project):
    """有明确Web启动入口时，不把备用项目XML当作已生效的依赖装配。"""

    root, catalog, _ = dependency_project
    web = root / 'src/main/webapp/WEB-INF/web.xml'
    web.parent.mkdir(parents=True)
    web.write_text('<web-app><context-param><param-name>contextConfigLocation</param-name><param-value>classpath:active.xml</param-value></context-param></web-app>')
    resources = root / 'src/main/resources'
    resources.mkdir(parents=True)
    (resources / 'active.xml').write_text('<beans/>')
    (resources / 'unused.xml').write_text('<beans><import resource="classpath:client.xml"/></beans>')
    scanner = DependencyInterfaceScanner(root, {}, catalog)
    paths = [path for _, path, _ in scanner.resources()]
    assert paths == ['src/main/resources/active.xml']
    assert scanner._components == {}


def test_source_component_scan_activates_dependency_package(dependency_project):
    """源码显式扫描的依赖包参与装配，其他包保持未激活。"""

    root, catalog, _ = dependency_project
    (root / 'src/main/java/demo/Config.java').write_text('@ComponentScan(basePackages={"demo.client"}) class Config {}')
    scanner = DependencyInterfaceScanner(root, {}, catalog)
    scanner.resources()
    assert 'demo.client.RepositoryImpl' in scanner._components
    assert 'demo.config.AutoConfig' not in scanner._components


def test_spring_factories_activates_declared_auto_configuration(dependency_project):
    """传统spring.factories与Boot imports沿同一装配路径解析属性条件。"""

    root, catalog, artifact = dependency_project
    (root / 'src/main/java/demo/Boot.java').write_text('@EnableAutoConfiguration class Boot {}')
    # 隔离掉新格式入口，证明传统配置也能独立驱动扫描。
    with zipfile.ZipFile(artifact.binary) as archive:
        entries = {name: archive.read(name) for name in archive.namelist() if not name.endswith('AutoConfiguration.imports')}
    with zipfile.ZipFile(artifact.binary, 'w') as archive:
        for name, content in entries.items():
            archive.writestr(name, content)
        archive.writestr('META-INF/spring.factories', 'org.springframework.boot.autoconfigure.EnableAutoConfiguration=\\\n demo.config.AutoConfig')
    scanner = DependencyInterfaceScanner(root, {'demo.enabled': 'true'}, catalog)
    assert any(path == 'client.xml' for _, path, _ in scanner.resources())


@pytest.mark.parametrize('enabled', ['true', 'false'])
def test_source_import_chain_respects_conditions_and_ignores_orphan_config(dependency_project, enabled):
    """Boot只激活扫描或Import触达的源码配置，条件不满足及孤立包不触发JAR导入。"""

    root, catalog, _ = dependency_project
    sources = root / 'src/main/java'
    (sources / 'demo/Boot.java').write_text('package demo; @SpringBootApplication @Import(Config.class) class Boot {}')
    (sources / 'demo/Config.java').write_text('package demo; @Configuration @ConditionalOnProperty(name = "demo.enabled", havingValue = "true") @ImportResource("classpath:client.xml") class Config {}')
    orphan = sources / 'unused/Config.java'
    orphan.parent.mkdir()
    orphan.write_text('package unused; @Configuration @ImportResource("classpath:never.xml") class Config {}')
    scanner = DependencyInterfaceScanner(root, {'demo.enabled': enabled}, catalog)
    paths = [path for _, path, _ in scanner.resources()]
    assert ('client.xml' in paths) == (enabled == 'true')
    assert 'unused.Config' not in scanner._configurations


def test_nested_xml_profile_preserves_lines_and_does_not_activate_imports(dependency_project):
    """嵌套profile中的导入和远程声明都必须被过滤，活动配置的证据行号保持原值。"""

    root, catalog, _ = dependency_project
    xml = root / 'src/main/resources/root.xml'
    xml.parent.mkdir(parents=True)
    xml.write_text('<beans>\n<beans profile="prod">\n<import resource="classpath:client.xml"/>\n</beans>\n<bean class="demo.Unrelated"/>\n</beans>')
    scanner = DependencyInterfaceScanner(root, {'spring.profiles.active': 'qa'}, catalog)
    documents = scanner.resources()
    assert len(documents) == 1
    assert 'classpath:client.xml' not in documents[0][2]
    assert documents[0][2].splitlines()[4] == '<bean class="demo.Unrelated"/>'
    assert scanner._components == {}


def test_xml_bean_activates_source_import_resource(dependency_project):
    """XML显式配置bean能进入本项目的ImportResource，避免只查二进制导致漏扫。"""

    root, catalog, _ = dependency_project
    (root / 'src/main/java/demo/Config.java').write_text('package demo; @ImportResource("classpath:client.xml") class Config {}')
    web = root / 'src/main/webapp/WEB-INF/web.xml'
    web.parent.mkdir(parents=True)
    web.write_text('<web-app><context-param><param-name>contextConfigLocation</param-name><param-value>classpath:root.xml</param-value></context-param></web-app>')
    xml = root / 'src/main/resources/root.xml'
    xml.parent.mkdir(parents=True)
    xml.write_text('<beans><bean class="demo.Config"/></beans>')
    scanner = DependencyInterfaceScanner(root, {}, catalog)
    assert any(path == 'client.xml' for _, path, _ in scanner.resources())


def test_self_closing_reference_registers_proven_methods_and_reports_overloads(dependency_project, monkeypatch):
    """完整接口引用展开唯一Path方法，重载明确报告缺口且不随意选择参数签名。"""

    root, catalog, _ = dependency_project
    xml = root / 'src/main/resources/root.xml'
    xml.parent.mkdir(parents=True)
    xml.write_text('<beans xmlns:sof="urn:sof"><sof:reference gsName="dsf.remote" serviceName="trade" version="1" interface="demo.api.Remote"/></beans>')
    scanner = DependencyInterfaceScanner(root, {}, catalog)

    def bound_scanner(source_root, properties):
        """使用fixture的真实二进制classpath，不让测试依赖本机Maven状态。"""
        return scanner

    monkeypatch.setattr('opentest.adapters.dependency_interfaces.DependencyInterfaceScanner', bound_scanner)
    operations, warnings = DsfSourceDiscoverer()._discover_reference_operations('caller', root, {})
    assert [operation.action for operation in operations] == ['query']
    assert operations[0].request_schema['properties']['orderId']['type'] == 'integer'
    assert any('demo.api.Remote#update' in warning and '重载' in warning for warning in warnings)


@pytest.mark.parametrize('declaration,active', [
    ('@ConditionalOnProperty("demo.enabled")', False),
    ('@ConditionalOnProperty(value="demo.enabled")', False),
    ('@ConditionalOnClass(Use.class)', True),
    ('@ConditionalOnMissingClass("demo.Use")', False),
])
def test_source_conditions_use_shorthand_and_project_classpath(dependency_project, declaration, active):
    """静态条件联合项目与JAR可见类型；简写属性为false时不得激活客户端。"""

    root, catalog, _ = dependency_project
    (root / 'src/main/java/demo/Config.java').write_text(
        'package demo; ' + declaration + ' @ImportResource("classpath:client.xml") class Config {}')
    scanner = DependencyInterfaceScanner(root, {'demo.enabled': 'false'}, catalog)
    assert any(path == 'client.xml' for _, path, _ in scanner.resources()) == active


@pytest.mark.parametrize('entry', ['xml', 'import'])
def test_explicit_binary_component_maps_repository_implementation(dependency_project, entry):
    """XML bean与Import显式装配实现时都能从项目注入接口追到远程边界。"""

    root, catalog, _ = dependency_project
    if entry == 'xml':
        xml = root / 'src/main/resources/root.xml'
        xml.parent.mkdir(parents=True)
        xml.write_text('<beans><bean class="demo.client.RepositoryImpl"/></beans>')
    else:
        (root / 'src/main/java/demo/Config.java').write_text(
            'package demo; @Import(demo.client.RepositoryImpl.class) class Config {}')
    scanner = DependencyInterfaceScanner(root, {}, catalog)
    scanner.resources()
    operation = DsfOperationDefinition(operation_id='dsf:remote:trade:query', provider_system_id='remote',
        gs_name='dsf.remote', service_name='trade', version='1', action='query',
        source_refs=[SourceReference(path='reference.xml', symbol='demo.api.Remote#query', line=1)])
    assert scanner.enrich([operation])[0].wrapper_symbols == ['demo.client.Repository#find']


@pytest.mark.parametrize('annotation', [
    '@SpringBootApplication(exclude=demo.config.AutoConfig.class)',
    '@SpringBootApplication(excludeName={"demo.config.AutoConfig"})',
    '@EnableAutoConfiguration(exclude=demo.config.AutoConfig.class)',
    '@EnableAutoConfiguration(excludeName="demo.config.AutoConfig")',
])
def test_boot_annotation_exclusions_do_not_activate_client(dependency_project, annotation):
    """Boot两种入口的类名与字符串排除都先于自动配置导入生效。"""

    root, catalog, _ = dependency_project
    (root / 'src/main/java/demo/Boot.java').write_text('package demo; ' + annotation + ' class Boot {}')
    scanner = DependencyInterfaceScanner(root, {'demo.enabled': 'true'}, catalog)
    assert not any(path == 'client.xml' for _, path, _ in scanner.resources())
    assert 'demo.config.AutoConfig' not in scanner._components
    assert scanner._component_boundaries() == []


def test_boot_with_unrelated_parameter_keeps_default_package_scan(dependency_project):
    """没有显式扫描包的Boot注解即使带其他参数，仍扫描同包的普通配置类。"""

    root, catalog, _ = dependency_project
    (root / 'src/main/java/demo/Boot.java').write_text('package demo; @SpringBootApplication(proxyBeanMethods=false) class Boot {}')
    (root / 'src/main/java/demo/Config.java').write_text(
        'package demo; @Configuration @ImportResource("classpath:client.xml") class Config {}')
    scanner = DependencyInterfaceScanner(root, {'demo.enabled': 'false'}, catalog)
    assert any(path == 'client.xml' for _, path, _ in scanner.resources())
